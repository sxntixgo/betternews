"""Why the reading list is empty.

An empty list has many causes and they need different actions: nothing polled
yet, nothing scored yet, everything scored below the threshold, everything read.
Showing a blank page for all of them is how a broken model went unnoticed three
separate times on this install.

Read-only. Every check is a count or a setting lookup, so this is cheap enough to
run whenever the list comes back empty.
"""

import logging

from sqlalchemy import func, select, text

from app import llm_config
from app.db import get_setting
from app.models import articles as A
from app.models import feeds as F

log = logging.getLogger(__name__)


def counts(db) -> dict:
    row = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE status = 'new')        AS unscored,
               COUNT(*) FILTER (WHERE status = 'scored')     AS unsummarized,
               COUNT(*) FILTER (WHERE status = 'hidden')     AS hidden,
               COUNT(*) FILTER (WHERE status = 'summarized') AS ready,
               COUNT(*)                                      AS total
        FROM articles
    """)).mappings().first()
    return dict(row) if row else {}


def last_run(db) -> dict | None:
    row = db.execute(text("""
        SELECT started_at, finished_at, scored_n, summarized_n, skipped
        FROM pipeline_runs ORDER BY started_at DESC LIMIT 1
    """)).mappings().first()
    return dict(row) if row else None


def model_problems(db, installed: list[str] | None) -> list[dict]:
    """Jobs whose model is not on the server.

    `installed` empty means Ollama did not answer — a different problem, and one
    the caller reports separately rather than flagging every job as broken.
    """
    if not installed:
        return []
    return [
        {"label": r["action"].label, "model": r["model"]}
        for r in llm_config.current(db, installed) if r["missing"]
    ]


def diagnose(db, *, user_id: int, visible: int) -> dict | None:
    """A single explanation for an empty list, or None when nothing is wrong.

    Ordered by what the reader should act on first: no feeds beats an unreachable
    Ollama, which beats a misconfigured model, which beats simply waiting.
    """
    if visible:
        return None

    from app import ollama_client
    from app.pipeline import ollama_base

    feeds = db.execute(select(func.count()).select_from(F)).scalar_one()
    if not feeds:
        return {"kind": "no_feeds",
                "title": "No feeds yet",
                "detail": "Add a feed and the reader will start filling up.",
                "action": ("Manage feeds", "/manage-feeds"), "admin_only": True}

    c = counts(db)
    if not c.get("total"):
        return {"kind": "not_polled",
                "title": "Nothing fetched yet",
                "detail": "The feeds are set up but no articles have arrived. "
                          "Polling runs on a schedule; Refresh starts it now.",
                "action": ("Refresh", None), "admin_only": True}

    # Something is waiting on the LLM. Work out whether it *can* run.
    if c.get("unscored") or c.get("unsummarized"):
        base = ollama_base(db)
        ok, message, installed = ollama_client.probe(base)
        pending = c.get("unscored", 0) + c.get("unsummarized", 0)

        if not ok:
            return {"kind": "ollama_unreachable",
                    "title": f"{pending} article{'s' if pending != 1 else ''} waiting — Ollama is unreachable",
                    "detail": message,
                    "action": ("Ollama settings", "/settings"), "admin_only": True}

        problems = model_problems(db, installed)
        if problems:
            names = ", ".join(sorted({p["model"] for p in problems}))
            labels = [p["label"] for p in problems]
            jobs = ", ".join(labels[:-1]) + f" and {labels[-1]}" if len(labels) > 1 else labels[0]
            verb = "is" if len(labels) == 1 else "are"
            return {"kind": "model_missing",
                    "title": f"{pending} article{'s' if pending != 1 else ''} waiting "
                             f"— a model is not installed",
                    "detail": f"{jobs} {verb} set to use {names}, which this Ollama "
                              f"does not have, so every call fails and nothing "
                              f"progresses. Installed: {', '.join(installed)}.",
                    "action": ("Choose a model", "/settings"), "admin_only": True}

        run = last_run(db)
        when = "" if not run else f" Last run finished {run.get('finished_at')}."
        return {"kind": "processing",
                "title": f"{pending} article{'s' if pending != 1 else ''} being processed",
                "detail": f"Scoring and summarizing run in the background."
                          f"{when} This page updates as they complete.",
                "action": None, "admin_only": False}

    if c.get("hidden"):
        return {"kind": "all_hidden",
                "title": f"All {c['hidden']} articles scored below your threshold",
                "detail": "Nothing cleared the relevance bar. Lower the threshold, "
                          "or look at what was filtered out.",
                "action": ("See hidden articles", "/?hidden=1"), "admin_only": False}

    return {"kind": "caught_up",
            "title": "You're all caught up",
            "detail": "Everything has been read or dismissed.",
            "action": None, "admin_only": False}

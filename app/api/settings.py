"""The settings panels.

Deliberately seven bespoke endpoints rather than a generic
`PUT /settings/{key}`. Half of these are not stores at all: `ollama/test` probes
without saving, `retention/prune` deletes rows, `models/recommended` computes,
and `topics` writes a different table entirely. A generic endpoint would need a
special case for most of them, and would happily accept a typo'd key that
nothing ever reads.

All of it is admin-only, as on the HTML side.
"""

from flask import jsonify, request

from app import llm_config, ollama_client, retention, topics as topics_mod
from app.api import api_admin, bp, error
from app.db import get_db, get_setting, set_setting
from app.repo import users as user_repo
from app.pipeline import DEFAULT_SCORING_MODEL, DEFAULT_SUMMARY_MODEL, ollama_base


def _flag(db, key: str) -> bool:
    return get_setting(db, key, "") == "1"


def _set_flag(db, key: str, value) -> None:
    set_setting(db, key, "1" if value else "")


# ── Ollama connection ─────────────────────────────────────────────────────────

@bp.get("/settings/ollama")
@api_admin
def ollama_get():
    db = get_db()
    host = (get_setting(db, "ollama_host", "") or "").strip()
    port = (get_setting(db, "ollama_port", "") or "").strip()
    return jsonify({
        "host": host,
        "port": port,
        # Blank means "fall back to the environment", which is worth saying
        # rather than showing empty boxes and letting someone guess.
        "using_env": not (host and port),
        "env_base": ollama_client.OLLAMA_BASE,
        "active_base": ollama_base(db),
    })


@bp.post("/settings/ollama")
@api_admin
def ollama_save():
    db = get_db()
    body = request.get_json(silent=True) or {}
    host = (body.get("host") or "").strip()
    port = str(body.get("port") or "").strip()
    if host or port:
        try:
            ollama_client.compose_base_url(host, port)
        except ValueError as exc:
            return error(str(exc), 400)
    set_setting(db, "ollama_host", host)
    set_setting(db, "ollama_port", port)
    db.commit()
    return ollama_get()


@bp.post("/settings/ollama/test")
@api_admin
def ollama_test():
    """Probe what is in the form, without saving it.

    Saving first and testing after is how a working configuration gets replaced
    by a broken one.
    """
    body = request.get_json(silent=True) or {}
    host = (body.get("host") or "").strip()
    port = str(body.get("port") or "").strip()
    try:
        base = (ollama_client.compose_base_url(host, port) if (host or port)
                else ollama_client.OLLAMA_BASE)
    except ValueError as exc:
        return error(str(exc), 400)
    ok, message, models = ollama_client.probe(base)
    return jsonify({"ok": ok, "message": message, "models": models, "base": base})


# ── Per-job models ────────────────────────────────────────────────────────────

@bp.get("/settings/models")
@api_admin
def models_get():
    """Every job, its model, and whether that model is actually installed.

    The mismatch this surfaces -- a configured model that is not pulled -- made
    every scoring call fail silently for six weeks.
    """
    db = get_db()
    installed = ollama_client.list_models(ollama_base(db))
    actions = []
    for action in llm_config.ACTIONS:
        current = llm_config.model_for(db, action.id)
        suggested, why = llm_config.recommend(action.id, installed)
        actions.append({
            "id": action.id,
            "label": action.label,
            "description": action.description,
            "current": current,
            "installed": current in installed if installed else None,
            "recommended": suggested,
            "why": why,
        })
    return jsonify({
        "actions": actions,
        "installed": installed,
        "defaults": {"scoring": DEFAULT_SCORING_MODEL, "summary": DEFAULT_SUMMARY_MODEL},
    })


@bp.post("/settings/models")
@api_admin
def models_save():
    db = get_db()
    body = request.get_json(silent=True) or {}
    known = {a.id for a in llm_config.ACTIONS}
    unknown = set(body) - known
    if unknown:
        return error(f"Unknown job(s): {', '.join(sorted(unknown))}", 400)
    for action_id, model in body.items():
        set_setting(db, f"model_{action_id}", (model or "").strip())
    db.commit()
    return models_get()


@bp.post("/settings/models/recommended")
@api_admin
def models_use_recommended():
    """Apply every recommendation at once.

    With no Ollama reachable there is nothing to recommend, and writing
    guesses would be worse than doing nothing -- so it reports zero.
    """
    db = get_db()
    installed = ollama_client.list_models(ollama_base(db))
    applied = 0
    for action in llm_config.ACTIONS:
        suggested, _ = llm_config.recommend(action.id, installed)
        if suggested:
            set_setting(db, f"model_{action.id}", suggested)
            applied += 1
    db.commit()
    return jsonify({"applied": applied})


# ── Reader behaviour ──────────────────────────────────────────────────────────

@bp.get("/settings/reader")
@api_admin
def reader_get():
    """Headlines, padding and notifications in one call.

    Three separate HTML panels, but one screen's worth of toggles, and a client
    that had to make three requests to draw one section would be paying for the
    server's template layout.
    """
    db = get_db()
    from app import content_filter
    return jsonify({
        "declickbait": _flag(db, "declickbait_enabled"),
        "content_filter_mode": get_setting(db, "content_filter_mode",
                                           content_filter.MODE_REMOVE),
        "content_filter_modes": sorted(content_filter.MODES),
        "content_filter_llm": _flag(db, "content_filter_llm"),
        "notify_high_score": _flag(db, "notify_high_score"),
    })


@bp.post("/settings/reader")
@api_admin
def reader_save():
    from app import content_filter

    db = get_db()
    body = request.get_json(silent=True) or {}
    if "declickbait" in body:
        _set_flag(db, "declickbait_enabled", body["declickbait"])
    if "content_filter_mode" in body:
        mode = body["content_filter_mode"]
        if mode not in content_filter.MODES:
            return error(f"mode must be one of: {', '.join(sorted(content_filter.MODES))}", 400)
        set_setting(db, "content_filter_mode", mode)
    if "content_filter_llm" in body:
        _set_flag(db, "content_filter_llm", body["content_filter_llm"])
    if "notify_high_score" in body:
        _set_flag(db, "notify_high_score", body["notify_high_score"])
    db.commit()
    return reader_get()


# ── Retention ─────────────────────────────────────────────────────────────────

@bp.get("/settings/retention")
@api_admin
def retention_get():
    db = get_db()
    return jsonify({
        "days": retention.retention_days(db),
        # Ships inert: the default window is shorter than most existing
        # corpora, so the first run would otherwise delete nearly everything.
        "confirmed": retention.is_confirmed(db),
        "preview": retention.preview(db),
    })


@bp.post("/settings/retention")
@api_admin
def retention_save():
    db = get_db()
    body = request.get_json(silent=True) or {}
    if "days" in body:
        try:
            days = int(body["days"])
        except (TypeError, ValueError):
            return error("days must be a whole number.", 400)
        if days < 0:
            return error("days cannot be negative.", 400)
        set_setting(db, retention.SETTING_DAYS, str(days))
    if "confirmed" in body:
        retention.set_confirmed(db, bool(body["confirmed"]))
    db.commit()
    return retention_get()


@bp.post("/settings/retention/prune")
@api_admin
def retention_prune():
    """Delete now, rather than waiting for the schedule.

    Refuses while unconfirmed: this is the one endpoint here that destroys
    articles, and the confirmation exists because the default window would take
    most of an existing corpus with it.
    """
    db = get_db()
    if not retention.is_confirmed(db):
        return error("Confirm the retention policy before pruning.", 409)
    removed = retention.prune(db)
    return jsonify({"removed": removed})


@bp.post("/settings/retention/clear-read")
@api_admin
def retention_clear_read():
    db = get_db()
    body = request.get_json(silent=True) or {}
    if body.get("all_users"):
        ids = [u["id"] for u in user_repo.all_with_stats(db)]
    else:
        ids = [int(v) for v in (body.get("user_ids") or [])]
    if not ids:
        return error("Pass user_ids, or all_users: true.", 400)
    # Takes a list, not a single id: clearing for several readers at once is the
    # normal case on a shared instance.
    removed = retention.clear_read(db, ids)
    db.commit()
    return jsonify({"cleared": removed})


# ── Topic rules ───────────────────────────────────────────────────────────────

@bp.get("/settings/topics")
@api_admin
def topics_get():
    db = get_db()
    # counts() already joins the rules, so there is no second lookup to keep in
    # step with it.
    return jsonify({"topics": [
        {"topic": r["topic"], "articles": r["n"],
         "muted": bool(r["muted"]), "adjustment": float(r["adjustment"])}
        for r in topics_mod.counts(db)
    ]})


@bp.post("/settings/topics")
@api_admin
def topics_save():
    """Mute, boost or clear a rule — or tidy the whole vocabulary.

    These are rules over every reader's list, unlike the per-reader stances on
    the profile page, which is why they live behind admin.
    """
    db = get_db()
    body = request.get_json(silent=True) or {}
    action = body.get("action", "")

    if action == "renormalize":
        n = topics_mod.renormalize_all(db)
        db.commit()
        return jsonify({"renormalized": n})

    topic = (body.get("topic") or "").strip()
    if not topic:
        return error("topic is required.", 400)

    if action == "clear":
        topics_mod.delete_rule(db, topic)
    elif action == "mute":
        topics_mod.set_rule(db, topic, muted=True)
    elif action == "boost":
        try:
            adjustment = float(body.get("adjustment", 0.1))
        except (TypeError, ValueError):
            return error("adjustment must be a number.", 400)
        topics_mod.set_rule(db, topic, adjustment=adjustment)
    else:
        return error("action must be mute, boost, clear or renormalize.", 400)

    db.commit()
    return topics_get()

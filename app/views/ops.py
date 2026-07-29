"""Operational surfaces: health, pipeline control, insights, Ollama log."""

import logging
from app import (auth, call_log, digest as digest_mod, export as export_mod,
                 extract, health, insights, pipeline_status, retention,
                 topics as topics_mod, user_topics)
from app.db import get_db, get_setting, set_setting
from app.repo import articles as art_repo, users as user_repo
from flask import (Blueprint, current_app, g, redirect, render_template,
                   request, Response, url_for)
from sqlalchemy import text as sql

from app.views import bp, current_user_id


log = logging.getLogger(__name__)


@bp.get("/status")
@auth.login_required
def status():
    db = get_db()
    counts = {r["status"]: r["n"] for r in art_repo.status_counts(db)}
    last_poll = db.execute(sql(
        "SELECT MAX(last_polled_at) AS t FROM feeds"
    )).scalar()
    last_pipeline = get_setting(db, "last_pipeline_run_at", "") or None
    notify = []
    if get_setting(db, "notify_high_score", "") == "1":
        from app.pipeline import HIGH_SCORE_NOTIFY
        uid = current_user_id(db)
        rows = art_repo.high_score_unnotified(db, uid, HIGH_SCORE_NOTIFY)
        notify = [{"id": r["id"], "title": r["clean_title"] or r["title"],
                   "score": r["score"]} for r in rows]
        if notify:
            art_repo.mark_notified(db, uid, [n["id"] for n in notify])
            db.commit()
    feed_count = db.execute(sql("SELECT COUNT(*) FROM feeds")).scalar()
    wants_json = "application/json" in request.headers.get("Accept", "")
    if wants_json:
        from flask import jsonify
        return jsonify({
            "high_score": notify,
            "last_poll_at": last_poll,
            "last_pipeline_run_at": last_pipeline,
            "feed_count": feed_count,
            "article_counts": counts,
        })
    return render_template(
        "_status.html",
        last_poll=last_poll,
        last_pipeline=last_pipeline,
        feed_count=feed_count,
        counts=counts,
    )


@bp.get("/health")
def healthcheck():
    """Liveness *and* ingestion. Public: the container healthcheck calls it.

    Returning 200 while nothing has been ingested for weeks is how the June
    outage stayed invisible.
    """
    db = get_db()
    st = health.ingestion_status(db)
    body = {
        "status": "ok" if st["healthy"] else "degraded",
        "feeds_total": st["total"],
        "feeds_paused": st["paused"],
        "last_success_at": st["last_success_at"].isoformat() if st["last_success_at"] else None,
        "ingestion_stale": st["stale"],
    }
    from flask import jsonify
    return jsonify(body), (200 if st["healthy"] else 503)


@bp.post("/poll")
@auth.admin_required
def manual_poll():
    import threading
    from app.feeds import poll_all_feeds
    from app.pipeline import run_pipeline

    app = current_app._get_current_object()

    def _run():
        try:
            poll_all_feeds(app)
            run_pipeline(app)
        except Exception as exc:
            log.error("Manual poll failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
    return Response("ok", status=200)


@bp.post("/rescore-hidden")
@auth.admin_required
def rescore_hidden():
    """Reset all hidden articles to 'new' so the next pipeline run re-scores them
    against the current preference profile."""
    import threading
    from app.pipeline import run_pipeline

    db = get_db()
    n = art_repo.rescore_hidden(db)
    db.commit()

    app = current_app._get_current_object()

    def _run():
        try:
            run_pipeline(app)
        except Exception as exc:
            log.error("Rescore failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
    return Response(f"requeued {n} articles", status=200)


@bp.get("/insights")
@auth.admin_required
def insights_page():
    """Is the ranking any good? Measured against your votes."""
    db = get_db()
    from app.pipeline import SCORE_THRESHOLD
    current = float(get_setting(db, "score_threshold", str(SCORE_THRESHOLD))
                    or SCORE_THRESHOLD)
    return render_template(
        "insights.html",
        histogram=insights.score_histogram(db),
        threshold=current,
        agreement=insights.agreement(db, current),
        suggestion=insights.suggest_threshold(db),
        per_feed=insights.per_feed(db),
        per_topic=insights.per_topic(db),
        pipeline=insights.pipeline_health(db),
        runs=insights.recent_runs(db),
        llm_error=__import__("app.pipeline", fromlist=["x"]).last_llm_error(db),
    )


@bp.post("/insights/threshold")
@auth.admin_required
def insights_apply_threshold():
    """A4: adopt the swept threshold in one click."""
    db = get_db()
    raw = request.form.get("threshold", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return Response("threshold must be a number", status=400)
    if not 0.0 <= value <= 1.0:
        return Response("threshold must be between 0.0 and 1.0", status=400)
    set_setting(db, "score_threshold", str(value))
    db.commit()
    return Response(f"threshold set to {value}", status=200)


@bp.get("/ollama-log")
@auth.admin_required
def ollama_log():
    """What was actually sent to Ollama and what came back."""
    db = get_db()
    only_failed = request.args.get("failed") == "1"
    return render_template(
        "ollama_log.html",
        calls=call_log.recent(db, failures_only=only_failed),
        summary=call_log.summary(db),
        enabled=call_log.enabled(db),
        only_failed=only_failed,
        keep=call_log.KEEP,
        # An empty log has two very different meanings: no calls are being made,
        # or none are needed. The queue is what tells them apart.
        queue=pipeline_status.counts(db),
        last_run=pipeline_status.last_run(db),
    )


@bp.post("/ollama-log/toggle")
@auth.admin_required
def ollama_log_toggle():
    db = get_db()
    set_setting(db, call_log.SETTING,
                "1" if request.form.get("enabled") == "1" else "")
    db.commit()
    return redirect(url_for("main.ollama_log"))


@bp.post("/ollama-log/clear")
@auth.admin_required
def ollama_log_clear():
    db = get_db()
    call_log.clear(db)
    db.commit()
    return redirect(url_for("main.ollama_log"))

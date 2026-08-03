"""Everything the reading list needs around it: feeds, topics, the digest."""

import logging

from flask import current_app, jsonify, request
from sqlalchemy import text as sql

from app import digest as digest_mod, llm_config, presenters, user_topics
from app.api import api_admin, api_auth, bp, current_api_user, error, serializers
from app.db import get_db, get_setting
from app.pipeline import ollama_base
from app.repo import articles as art_repo

log = logging.getLogger(__name__)


@bp.get("/feeds")
@api_auth
def list_feeds():
    db = get_db()
    rows = art_repo.sidebar_counts(db, current_api_user())
    return jsonify({
        "feeds": [serializers.feed(r) for r in rows],
        "unread": sum((r["unread"] or 0) for r in rows),
        "saved": sum((r["saved"] or 0) for r in rows),
        "hidden": sum((r["hidden"] or 0) for r in rows),
    })


@bp.get("/topics")
@api_auth
def list_topics():
    """This reader's stances, for the profile screen."""
    db = get_db()
    uid = current_api_user()
    return jsonify({"topics": [
        {"topic": r["topic"], "stance": r["stance"], "articles": r["articles"],
         "likes": r["likes"], "dislikes": r["dislikes"]}
        for r in user_topics.for_profile(db, uid)
    ]})


@bp.post("/topics/<topic>/stance")
@api_auth
def set_stance(topic: str):
    db = get_db()
    uid = current_api_user()
    stance = (request.get_json(silent=True) or {}).get("stance")
    try:
        user_topics.set_stance(db, uid, topic, stance)
    except ValueError as exc:
        return error(str(exc), 400)
    db.commit()
    # A stance changes which articles are unread, so the cached digest is stale.
    digest_mod.clear(db, uid)
    db.commit()
    return jsonify({"topic": topic, "stance": stance})


@bp.get("/digest")
@api_auth
def digest():
    """"What you missed". Cached against the unread set, so this is cheap until
    that set changes."""
    db = get_db()
    uid = current_api_user()
    body, count, from_cache = digest_mod.generate(
        db, uid, model=llm_config.model_for(db, "digest"), base_url=ollama_base(db),
    )
    db.commit()
    return jsonify({
        "body": body,
        "article_count": count,
        "cached": from_cache,
        "articles": [{"id": r["id"], "url": r["url"]}
                     for r in digest_mod.unread_for(db, uid)],
    })


@bp.get("/me")
@api_auth
def me():
    """Who this token belongs to. The first call a client makes."""
    from app.repo import users as user_repo
    db = get_db()
    uid = current_api_user()
    user = user_repo.get(db, uid)
    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        # After an admin reset, the server UI blocks everything until this is
        # changed. Once the HTML UI is gone there is nowhere else to say so, so
        # the client has to be able to enforce the same thing.
        "must_change_password": bool(user["must_change_password"]),
        "declickbait": presenters.declickbait(db),
        "content_filter_mode": presenters.content_filter_mode(db),
    })


@bp.post("/digest/dismiss")
@api_auth
def digest_dismiss():
    """Drop the cached briefing so the next request rebuilds it."""
    db = get_db()
    digest_mod.clear(db, current_api_user())
    db.commit()
    return jsonify({"ok": True})


@bp.get("/status")
@api_auth
def status():
    """What the reading client polls to know when new articles have landed.

    `last_pipeline_run_at` advancing is the signal to refetch the list, and
    `high_score` is returned once per reader per article -- the server tracks
    that, so there is no client-side dedupe to get wrong.
    """
    db = get_db()
    uid = current_api_user()
    counts = {r["status"]: r["n"] for r in art_repo.status_counts(db)}
    notify = []
    if get_setting(db, "notify_high_score", "") == "1":
        from app.pipeline import HIGH_SCORE_NOTIFY
        rows = art_repo.high_score_unnotified(db, uid, HIGH_SCORE_NOTIFY)
        notify = [{"id": r["id"], "title": r["clean_title"] or r["title"],
                   "score": r["score"]} for r in rows]
        if notify:
            art_repo.mark_notified(db, uid, [n["id"] for n in notify])
            db.commit()
    last_poll = db.execute(sql("SELECT MAX(last_polled_at) AS t FROM feeds")).scalar()
    return jsonify({
        "high_score": notify,
        "last_poll_at": last_poll.isoformat() if last_poll else None,
        "last_pipeline_run_at": get_setting(db, "last_pipeline_run_at", "") or None,
        "feed_count": db.execute(sql("SELECT COUNT(*) FROM feeds")).scalar(),
        "article_counts": counts,
    })


@bp.post("/poll")
@api_admin
def poll():
    """Fetch feeds and run the pipeline, in the background.

    Admin-only, as on the HTML side: it is the one button that costs GPU time.
    """
    import threading
    from app.feeds import poll_all_feeds
    from app.pipeline import run_pipeline

    app_obj = current_app._get_current_object()

    def _run():
        try:
            poll_all_feeds(app_obj)
            run_pipeline(app_obj)
        except Exception as exc:
            log.error("Manual poll failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"started": True})


@bp.post("/rescore-hidden")
@api_admin
def rescore_hidden():
    """Reset hidden articles to 'new' so the next run re-scores them.

    Mirrors the HTML route: the requeue happens here, synchronously, so the
    count returned is real; only the pipeline run goes to a thread. Doing the
    requeue in the background too would mean answering with a number nothing
    had produced yet.
    """
    import threading
    from app.pipeline import run_pipeline

    db = get_db()
    n = art_repo.rescore_hidden(db)
    db.commit()

    app_obj = current_app._get_current_object()

    def _run():
        try:
            run_pipeline(app_obj)
        except Exception as exc:
            log.error("Rescore-hidden failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"requeued": n})

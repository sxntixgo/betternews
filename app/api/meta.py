"""Everything the reading list needs around it: feeds, topics, the digest."""

from flask import jsonify, request

from app import digest as digest_mod, llm_config, presenters, user_topics
from app.api import api_auth, bp, current_api_user, error, serializers
from app.db import get_db
from app.pipeline import ollama_base
from app.repo import articles as art_repo


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
        "declickbait": presenters.declickbait(db),
        "content_filter_mode": presenters.content_filter_mode(db),
    })

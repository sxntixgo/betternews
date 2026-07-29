"""Reading: the list, one article, and acting on it."""

from flask import jsonify, request
from sqlalchemy import text as sql

from app import presenters
from app.api import api_auth, bp, current_api_user, error, serializers
from app.db import get_db, get_setting
from app.repo import articles as art_repo

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _limit() -> int:
    try:
        return max(1, min(MAX_LIMIT, int(request.args.get("limit", DEFAULT_LIMIT))))
    except ValueError:
        return DEFAULT_LIMIT


def _offset() -> int:
    try:
        return max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return 0


@bp.get("/articles")
@api_auth
def list_articles():
    """The reading list, paginated.

    `next_offset` is exact -- collapsing duplicates happens in SQL, so the
    offset counts articles rather than source rows. A client can page straight
    through without seeing anything twice.
    """
    db = get_db()
    uid = current_api_user()
    feed_arg = request.args.get("feed", "").strip()
    page = art_repo.list_for_user(
        db, uid,
        hidden=request.args.get("hidden") == "1",
        saved=request.args.get("saved") == "1",
        feed_id=int(feed_arg) if feed_arg.isdigit() else None,
        sort=request.args.get("sort", "date"),
        topic=request.args.get("topic", "").strip() or None,
        limit=_limit(), offset=_offset(),
    )
    declickbait = presenters.declickbait(db)
    return jsonify({
        "articles": [serializers.article(r, declickbait) for r in page],
        "next_offset": page.next_offset,
    })


@bp.get("/articles/<int:article_id>")
@api_auth
def get_article(article_id: int):
    """One article with its body, and marks it read -- same as opening the
    reader in the browser does."""
    db = get_db()
    uid = current_api_user()
    if not art_repo.exists(db, article_id):
        return error("No such article.", 404)

    # Marked read *before* the card is read back. The other order returned
    # state.read=false from the very call that set it, so every client had to
    # patch the value it had just been given.
    art_repo.mark_read(db, uid, article_id)
    row = art_repo.get_card(db, uid, article_id)

    # Mirrors views/reading.article_content deliberately, down to the columns it
    # reads. Any divergence here is the phone and the browser showing different
    # article bodies, which is the failure this whole layer exists to prevent.
    body = db.execute(sql(
        "SELECT title, full_text, raw_snippet, feed_content, aside_spans "
        "FROM articles WHERE id=:id"), {"id": article_id}).mappings().first()
    description = (body["raw_snippet"] or "").strip()
    full_text = body["full_text"] or body["feed_content"] or ""
    # Stripped against the *stored* title -- that is the wording the body may
    # duplicate, whichever title ends up displayed.
    content = presenters.clean_content(
        full_text, title=body["title"], description=description)

    declickbait = presenters.declickbait(db)
    blocks, asides = presenters.content_blocks(
        content,
        embeds_enabled=get_setting(db, "embeds_enabled", "") == "1",
        mode=presenters.content_filter_mode(db),
        stored_asides=body["aside_spans"],
    )
    db.commit()
    out = serializers.article_detail(row, blocks, asides, declickbait)
    out["description"] = description
    return jsonify(out)


def _state_change(article_id: int, fn):
    db = get_db()
    uid = current_api_user()
    if not art_repo.exists(db, article_id):
        return error("No such article.", 404)
    fn(db, uid, article_id)
    db.commit()
    return jsonify(serializers.article(
        art_repo.get_card(db, uid, article_id), presenters.declickbait(db)))


@bp.post("/articles/<int:article_id>/save")
@api_auth
def save(article_id: int):
    return _state_change(article_id, art_repo.toggle_saved)


@bp.post("/articles/<int:article_id>/dismiss")
@api_auth
def dismiss(article_id: int):
    return _state_change(article_id, art_repo.dismiss)


@bp.post("/articles/<int:article_id>/read")
@api_auth
def read(article_id: int):
    return _state_change(article_id, art_repo.mark_read)


@bp.post("/articles/<int:article_id>/vote")
@api_auth
def vote(article_id: int):
    body = request.get_json(silent=True) or {}
    value = body.get("value")
    if value not in (1, -1):
        return error("value must be 1 or -1.", 400)
    return _state_change(
        article_id, lambda db, uid, aid: art_repo.record_vote(db, uid, aid, value))

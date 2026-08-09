"""Reading: the list, one article, and acting on it."""

import logging
from datetime import datetime, timezone

from flask import Response, jsonify, request
from sqlalchemy import text as sql

from app import export as export_mod, pipeline_status, presenters
from app.api import api_auth, bp, current_api_user, error, serializers
from app.db import get_db
from app.repo import articles as art_repo

log = logging.getLogger(__name__)

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
        # The dismissed pile is its own list, asked for explicitly. It used to
        # be mixed into this one, greyed out, where it was most of what a
        # reader scrolled past.
        dismissed=request.args.get("dismissed") == "1",
    )
    declickbait = presenters.declickbait(db)
    return jsonify({
        "articles": [serializers.article(r, declickbait) for r in page],
        "next_offset": page.next_offset,
        # Why the list is empty, when it is. A bare "Nothing to read" is how a
        # misconfigured model went unnoticed three times -- the server knows the
        # difference between "no feeds", "Ollama unreachable", "still working"
        # and "caught up", and the client cannot work it out for itself.
        #
        # Only on the first page: an empty page two is the end of the list, not
        # a problem, and diagnosing it costs an Ollama probe.
        "diagnosis": _diagnosis(db, uid, len(page), _offset()),
    })


def _diagnosis(db, uid: int, visible: int, offset: int) -> dict | None:
    if offset:
        return None
    found = pipeline_status.diagnose(db, user_id=uid, visible=visible)
    if found is None:
        return None
    # The href is dropped on purpose. `diagnose` still names one because it was
    # written for server-rendered links; the client owns its own navigation and
    # has no URLs to link to. `kind` is the stable thing to branch on.
    label = found["action"][0] if found.get("action") else None
    return {
        "kind": found["kind"],
        "title": found["title"],
        "detail": found["detail"],
        "action": label,
        "admin_only": found["admin_only"],
    }


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


@bp.get("/search")
@api_auth
def search():
    """Full-text search, scoped to this reader.

    `websearch_to_tsquery` accepts quoted phrases and -exclusions and does not
    raise on malformed input, so there is nothing to sanitise here.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return error("q is required.", 400)
    db = get_db()
    rows = art_repo.search(db, current_api_user(), q, limit=_limit())
    declickbait = presenters.declickbait(db)
    return jsonify({"articles": [serializers.article(r, declickbait) for r in rows]})


@bp.post("/articles/dismiss-all")
@api_auth
def dismiss_all():
    """Dismiss everything in the list the caller is looking at.

    Takes the same filters as GET /articles on purpose: dismissing has to mean
    the list on screen, or it dismisses something the reader cannot see.
    """
    db = get_db()
    feed_arg = request.args.get("feed", "").strip()
    n = art_repo.dismiss_all(
        db, current_api_user(),
        int(feed_arg) if feed_arg.isdigit() else None,
        hidden=request.args.get("hidden") == "1",
        saved=request.args.get("saved") == "1",
        topic=request.args.get("topic", "").strip() or None,
    )
    db.commit()
    return jsonify({"dismissed": n})


@bp.get("/export")
@api_auth
def export():
    """Reading as a zip of Markdown, scoped to the caller.

    A bearer client cannot use <a download> -- the header would not travel -- so
    it fetches this and builds a Blob. The filename therefore has to be in
    Content-Disposition rather than the URL.
    """
    scope = request.args.get("scope", "saved")
    if scope not in export_mod.SCOPES:
        return error(f"scope must be one of: {', '.join(sorted(export_mod.SCOPES))}", 400)
    db = get_db()
    data, n = export_mod.build_zip(db, current_api_user(), scope)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    log.info("API export: %d articles (scope=%s)", n, scope)
    return Response(
        data, mimetype="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="betternews-{scope}-{stamp}.zip"'},
    )

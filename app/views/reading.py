"""The reading list itself: what to show, and acting on an article."""

import logging
from app import (auth, call_log, digest as digest_mod, export as export_mod,
                 extract, health, insights, pipeline_status, retention,
                 topics as topics_mod, user_topics)
from app import presenters
from app.db import get_db, get_setting, set_setting
from app.pipeline import DEFAULT_SCORING_MODEL, DEFAULT_SUMMARY_MODEL, ollama_base
from app.repo import articles as art_repo, users as user_repo
from datetime import datetime, timezone
from flask import (Blueprint, current_app, g, redirect, render_template,
                   request, Response, url_for)
from sqlalchemy import text as sql
from urllib.parse import quote

from app.views import bp, current_user_id


log = logging.getLogger(__name__)

_PAGE_SIZE = 50


@bp.get("/")
@auth.login_required
def index():
    return render_template("index.html")


@bp.get("/articles")
@auth.login_required
def articles():
    sort = request.args.get("sort", "date")
    order = "published_at DESC" if sort == "date" else "score DESC, published_at DESC"
    # ?hidden=1 means show ONLY hidden articles (the sidebar "Hidden" group),
    # not "include hidden in the normal list". ?saved=1 means show ONLY saved.
    show_hidden = request.args.get("hidden") == "1"
    show_saved = request.args.get("saved") == "1"
    statuses = (
        "('hidden')"
        if show_hidden else
        "('summarized', 'liked', 'disliked')"
    )
    try:
        offset = max(0, int(request.args.get("offset", "0")))
    except ValueError:
        offset = 0
    feed_arg = request.args.get("feed", "").strip()
    feed_id = int(feed_arg) if feed_arg.isdigit() else None
    topic = request.args.get("topic", "").strip() or None
    db = get_db()
    uid = current_user_id(db)
    declickbait = presenters.declickbait(db)
    rows = art_repo.list_for_user(
        db, uid, hidden=show_hidden, saved=show_saved, feed_id=feed_id,
        sort=sort, topic=topic,
        limit=_PAGE_SIZE, offset=offset,
    )
    next_offset = offset + _PAGE_SIZE if len(rows) == _PAGE_SIZE else None
    next_qs = ""
    if next_offset is not None:
        parts = [f"sort={sort}", f"offset={next_offset}"]
        if show_hidden:
            parts.append("hidden=1")
        if show_saved:
            parts.append("saved=1")
        if feed_arg.isdigit():
            parts.append(f"feed={int(feed_arg)}")
        if topic:
            # Without this, scrolling a topic view silently loads page 2 of
            # *everything* -- the filter looks like it forgot itself mid-list.
            parts.append(f"topic={quote(topic)}")
        next_qs = "&".join(parts)
    return render_template(
        "_articles.html",
        articles=[presenters.row_to_article(r, declickbait) for r in rows],
        next_qs=next_qs,
        is_first_page=(offset == 0),
        # Only diagnose the first page: page 2 being empty just means the end.
        status=(pipeline_status.diagnose(db, user_id=uid, visible=len(rows))
                if offset == 0 else None),
    )


@bp.get("/search")
@auth.login_required
def search():
    """Full-text search over title/summary/full_text using FTS5."""
    q = request.args.get("q", "").strip()
    if not q:
        return render_template(
            "_articles.html", articles=[], next_qs="", is_first_page=True
        )
    db = get_db()
    uid = current_user_id(db)
    declickbait = presenters.declickbait(db)
    try:
        rows = art_repo.search(db, uid, q, limit=_PAGE_SIZE)
    except Exception as exc:
        log.warning("Search failed for %r: %s", q, exc)
        rows = []
    return render_template(
        "_articles.html",
        articles=[presenters.row_to_article(r, declickbait) for r in rows],
        next_qs="",
        is_first_page=True,
    )


@bp.post("/article/<int:article_id>/save")
@auth.login_required
def article_save(article_id: int):
    """Toggle the saved/read-later flag on an article and return the refreshed card."""
    db = get_db()
    uid = current_user_id(db)
    if not art_repo.exists(db, article_id):
        return Response("not found", status=404)
    art_repo.toggle_saved(db, uid, article_id)
    db.commit()
    card = art_repo.get_card(db, uid, article_id)
    return render_template("_article_card.html",
                           article=presenters.row_to_article(card, presenters.declickbait(db)))


@bp.post("/article/<int:article_id>/dismiss")
@auth.login_required
def article_dismiss(article_id: int):
    """Mark a single article as dismissed. Used by the swipe-left gesture."""
    db = get_db()
    uid = current_user_id(db)
    if not art_repo.exists(db, article_id):
        return Response("not found", status=404)
    art_repo.dismiss(db, uid, article_id)
    db.commit()
    return Response("", status=200)


@bp.post("/vote/<int:article_id>/<value>")
@auth.login_required
def vote(article_id: int, value: str):
    try:
        value = int(value)
    except ValueError:
        return Response("invalid vote", status=400)
    if value not in (1, -1):
        return Response("invalid vote", status=400)
    db = get_db()
    uid = current_user_id(db)
    if not art_repo.exists(db, article_id):
        return Response("not found", status=404)
    art_repo.record_vote(db, uid, article_id, value)
    db.commit()
    row = art_repo.get_card(db, uid, article_id)
    return render_template("_article_card.html",
                           article=presenters.row_to_article(row, presenters.declickbait(db)))


@bp.get("/article/<int:article_id>/content")
@auth.login_required
def article_content(article_id: int):
    db = get_db()
    row = db.execute(sql(
        "SELECT title, url, full_text, raw_snippet, feed_content, clean_title, "
        "title_was_clickbait, aside_spans "
        "FROM articles WHERE id=:id"),
        {"id": article_id},
    ).mappings().first()
    if not row:
        return Response("Article not found.", status=404)
    art_repo.mark_read(db, current_user_id(db), article_id)
    db.commit()
    description = (row["raw_snippet"] or "").strip()
    full_text = row["full_text"] or row["feed_content"] or ""
    # Strip against the stored title — that's the wording the body may duplicate,
    # regardless of which title is displayed.
    content = presenters.clean_content(full_text, title=row["title"], description=description)
    embeds_enabled = get_setting(db, "embeds_enabled", "") == "1"
    title, original_title = presenters.resolve_title(dict(row), presenters.declickbait(db))
    mode = presenters.content_filter_mode(db)
    groups, aside_count = presenters.content_blocks(
        content, embeds_enabled, mode,
        row["aside_spans"],
    )
    return render_template(
        "_article_content.html",
        title=title,
        original_title=original_title,
        description=description,
        groups=groups,
        filter_mode=mode,
        aside_count=aside_count,
    )


@bp.get("/export/markdown")
@auth.login_required
def export_markdown():
    """Your reading, as Markdown files. Scoped to the calling user."""
    db = get_db()
    scope = request.args.get("scope", "saved")
    if scope not in export_mod.SCOPES:
        return Response("scope must be saved, liked or all", status=400)
    data, n = export_mod.build_zip(db, current_user_id(db), scope)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    log.info("Exported %d articles (scope=%s)", n, scope)
    return Response(
        data, mimetype="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="betterread-{scope}-{stamp}.zip"'},
    )


@bp.get("/digest")
@auth.login_required
def digest_fragment():
    """What you missed: everything unread, grouped into themes.

    Uses the cached copy unless the unread set has changed, so opening the page
    repeatedly does not cost repeated Ollama calls.
    """
    db = get_db()
    uid = current_user_id(db)
    from app import llm_config
    from app.pipeline import ollama_base
    body, count, from_cache = digest_mod.generate(
        db, uid, model=llm_config.model_for(db, "digest"), base_url=ollama_base(db),
        force=request.args.get("force") == "1",
    )
    db.commit()
    known = {r["id"]: r["url"] for r in digest_mod.unread_for(db, uid)}
    return render_template(
        "_digest.html",
        body=digest_mod.linkify(body, known) if body else None,
        count=count, from_cache=from_cache,
        made_at=(digest_mod.cached(db, uid) or {}).get("created_at"),
    )


@bp.post("/digest/dismiss")
@auth.login_required
def digest_dismiss():
    db = get_db()
    digest_mod.clear(db, current_user_id(db))
    db.commit()
    return Response("", status=200)


@bp.get("/count")
@auth.login_required
def article_count():
    db = get_db()
    return str(art_repo.unread_count(db, current_user_id(db)))


@bp.post("/dismiss-all")
@auth.login_required
def dismiss_all():
    """Mark every currently-listed article (summarized/liked/disliked) as
    'dismissed' so they disappear from the main view. Respects the current
    feed filter when ?feed=<id> is provided. Votes remain in the votes table
    so the preference signal is preserved."""
    db = get_db()
    feed_arg = request.args.get("feed", "").strip()
    feed_id = int(feed_arg) if feed_arg.isdigit() else None
    n = art_repo.dismiss_all(db, current_user_id(db), feed_id)
    db.commit()
    return Response(f"dismissed {n} articles", status=200)

"""Feed subscriptions, the sidebar tree, and OPML import/export."""

import xml.etree.ElementTree as ET
from app import (auth, call_log, digest as digest_mod, export as export_mod,
                 extract, health, insights, pipeline_status, retention,
                 topics as topics_mod, user_topics)
from app import opml
from app.db import get_db, get_setting, set_setting
from app.repo import articles as art_repo, users as user_repo
from flask import (Blueprint, current_app, g, redirect, render_template,
                   request, Response, url_for)
from html import escape
from sqlalchemy import text as sql

from app.views import bp, current_user_id



@bp.get("/manage-feeds")
@auth.admin_required
def manage_feeds():
    return render_template("manage_feeds.html")


@bp.get("/sidebar/feeds")
@auth.login_required
def sidebar_feeds():
    """Feed list with per-feed unread + hidden + saved counts for the left sidebar.
    Feeds are grouped by tag; feeds with no tags appear under 'Untagged'."""
    db = get_db()
    uid = current_user_id(db)
    rows = art_repo.sidebar_counts(db, uid)
    total_unread = sum((r["unread"] or 0) for r in rows)
    total_hidden = sum((r["hidden"] or 0) for r in rows)
    total_saved = sum((r["saved"] or 0) for r in rows)

    by_tag: dict[str, list] = {}
    untagged: list = []
    for r in rows:
        tags = _split_tags(r["tags"])
        if not tags:
            untagged.append(r)
            continue
        for t in tags:
            by_tag.setdefault(t, []).append(r)
    tag_groups = [(tag, by_tag[tag]) for tag in sorted(by_tag.keys())]

    return render_template(
        "_sidebar_feeds.html",
        feeds=rows,
        tag_groups=tag_groups,
        untagged=untagged,
        total_unread=total_unread,
        total_hidden=total_hidden,
        total_saved=total_saved,
    )


@bp.get("/feeds")
@auth.admin_required
def feeds_list():
    db = get_db()
    return render_template("_feeds.html", feeds=_all_feeds(db),
                           extraction=_feed_extract_health(db))


@bp.post("/feeds")
@auth.admin_required
def feeds_add():
    url = request.form.get("url", "").strip()
    if not url:
        return Response("url required", status=400)
    db = get_db()
    res = db.execute(
        sql("INSERT INTO feeds (url) VALUES (:url) ON CONFLICT (url) DO NOTHING"),
        {"url": url},
    )
    if not res.rowcount:
        return Response("feed already exists", status=409)
    db.commit()
    return render_template("_feeds.html", feeds=_all_feeds(db))


@bp.delete("/feeds/<int:feed_id>")
@auth.admin_required
def feeds_delete(feed_id: int):
    db = get_db()
    db.execute(sql("DELETE FROM feeds WHERE id=:id"), {"id": feed_id})
    db.commit()
    rows = _all_feeds(db)
    return render_template("_feeds.html", feeds=rows,
                           extraction=_feed_extract_health(db))


@bp.get("/feeds/opml")
@auth.admin_required
def feeds_export_opml():
    db = get_db()
    rows = db.execute(sql("SELECT url, title FROM feeds ORDER BY id")).mappings().all()
    return Response(
        opml.document(rows),
        mimetype="text/x-opml",
        headers={"Content-Disposition": 'attachment; filename="feeds.opml"'},
    )


@bp.post("/feeds/opml")
@auth.admin_required
def feeds_import_opml():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return Response("file required", status=400)
    db = get_db()
    try:
        added = opml.import_urls(db, opml.urls_from(upload.read()))
    except ValueError as exc:
        return Response(str(exc), status=400)
    return render_template("_feeds.html", feeds=_all_feeds(db), opml_added=added,
                           extraction=_feed_extract_health(db))


@bp.post("/feeds/<int:feed_id>/pause")
@auth.admin_required
def feed_pause(feed_id: int):
    """Pause polling for a feed. Idempotent."""
    db = get_db()
    db.execute(sql("UPDATE feeds SET paused=true WHERE id=:id"), {"id": feed_id})
    db.commit()
    rows = _all_feeds(db)
    return render_template("_feeds.html", feeds=rows,
                           extraction=_feed_extract_health(db))


@bp.post("/feeds/<int:feed_id>/resume")
@auth.admin_required
def feed_resume(feed_id: int):
    """Resume polling for a feed and reset its failure counter."""
    db = get_db()
    db.execute(
        sql("UPDATE feeds SET paused=false, consecutive_failures=0, "
            "last_error=NULL WHERE id=:id"),
        {"id": feed_id},
    )
    db.commit()
    rows = _all_feeds(db)
    return render_template("_feeds.html", feeds=rows,
                           extraction=_feed_extract_health(db))


@bp.post("/feeds/<int:feed_id>/threshold")
@auth.admin_required
def feed_set_threshold(feed_id: int):
    """Set per-feed score threshold. Empty string clears the override."""
    raw = request.form.get("score_threshold", "").strip()
    db = get_db()
    if raw == "":
        db.execute(sql("UPDATE feeds SET score_threshold=NULL WHERE id=:id"), {"id": feed_id})
    else:
        try:
            value = float(raw)
        except ValueError:
            return Response("threshold must be a number 0.0-1.0", status=400)
        if not 0.0 <= value <= 1.0:
            return Response("threshold must be 0.0-1.0", status=400)
        db.execute(
            sql("UPDATE feeds SET score_threshold=:v WHERE id=:id"),
            {"v": value, "id": feed_id},
        )
    db.commit()
    rows = _all_feeds(db)
    return render_template("_feeds.html", feeds=rows,
                           extraction=_feed_extract_health(db))


@bp.post("/feeds/<int:feed_id>/tags")
@auth.admin_required
def feed_set_tags(feed_id: int):
    """Set comma-separated tags on a feed. Empty string clears all tags."""
    raw = request.form.get("tags", "")
    normalized = _normalize_tags(raw)
    db = get_db()
    db.execute(
        sql("UPDATE feeds SET tags=:tags WHERE id=:id"),
        {"tags": normalized or None, "id": feed_id},
    )
    db.commit()
    rows = _all_feeds(db)
    return render_template("_feeds.html", feeds=rows,
                           extraction=_feed_extract_health(db))


def _feed_extract_health(db) -> dict:
    return {r["id"]: r for r in extract.health_by_feed(db)}


def _all_feeds(db):
    return db.execute(sql(
        "SELECT id, url, title, last_polled_at, last_success_at, last_error, "
        "consecutive_failures, paused, score_threshold, tags "
        "FROM feeds ORDER BY id"
    )).mappings().all()


def _normalize_tags(raw: str) -> str:
    """Normalize a free-form tags string to canonical comma-separated form.
    Splits on commas, trims, lowercases, drops empties, dedupes, sorts.
    Returns '' for input that produces no tags."""
    if not raw:
        return ""
    seen: list[str] = []
    for part in raw.split(","):
        t = part.strip().lower()
        if t and t not in seen:
            seen.append(t)
    seen.sort()
    return ",".join(seen)


def _split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p for p in raw.split(",") if p]

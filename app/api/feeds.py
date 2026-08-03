"""Feed subscriptions: adding, pausing, tagging, and OPML.

Every mutation is admin-only, as on the HTML side. Reading the list is not:
a reader needs the sidebar counts, and those come from /feeds.
"""

from datetime import datetime, timezone

from flask import Response, jsonify, request
from sqlalchemy import text as sql

from app import opml
from app.api import api_admin, api_auth, bp, error
from app import tags as tag_util
from app.db import get_db


def _feed_row(r) -> dict:
    return {
        "id": r["id"],
        "url": r["url"],
        "title": r["title"],
        "paused": bool(r["paused"]),
        # The health fields are here because a silent 43-day outage happened:
        # every feed auto-paused after a transient DNS failure and nothing said
        # so. A management screen that hides the error repeats that.
        "last_polled_at": r["last_polled_at"].isoformat() if r["last_polled_at"] else None,
        "last_success_at": r["last_success_at"].isoformat() if r["last_success_at"] else None,
        "last_error": r["last_error"],
        "consecutive_failures": r["consecutive_failures"],
        "score_threshold": r["score_threshold"],
        # tags is a comma-separated string, not an array -- list() on it
        # iterates characters, which is exactly what the first version did.
        "tags": tag_util.split(r["tags"]),
    }


def _all_feeds(db):
    return db.execute(sql(
        "SELECT id, url, title, last_polled_at, last_success_at, last_error, "
        "consecutive_failures, paused, score_threshold, tags "
        "FROM feeds ORDER BY id"
    )).mappings().all()


def _one(db, feed_id: int):
    return db.execute(sql(
        "SELECT id, url, title, last_polled_at, last_success_at, last_error, "
        "consecutive_failures, paused, score_threshold, tags "
        "FROM feeds WHERE id = :i"), {"i": feed_id}).mappings().first()


@bp.get("/feeds/manage")
@api_auth
def list_for_management():
    """Everything a management screen needs, health included."""
    db = get_db()
    return jsonify({"feeds": [_feed_row(r) for r in _all_feeds(db)]})


@bp.post("/feeds")
@api_admin
def add_feed():
    db = get_db()
    url = (request.get_json(silent=True) or {}).get("url", "").strip()
    if not url:
        return error("A feed URL is required.", 400)
    row = db.execute(sql(
        "INSERT INTO feeds (url) VALUES (:u) ON CONFLICT (url) DO NOTHING "
        "RETURNING id"), {"u": url}).first()
    if row is None:
        return error("That feed is already subscribed.", 409)
    db.commit()
    return jsonify(_feed_row(_one(db, row[0])))


@bp.delete("/feeds/<int:feed_id>")
@api_admin
def delete_feed(feed_id: int):
    db = get_db()
    if _one(db, feed_id) is None:
        return error("No such feed.", 404)
    db.execute(sql("DELETE FROM feeds WHERE id = :i"), {"i": feed_id})
    db.commit()
    return jsonify({"deleted": feed_id})


def _set_paused(feed_id: int, paused: bool):
    db = get_db()
    if _one(db, feed_id) is None:
        return error("No such feed.", 404)
    db.execute(sql("UPDATE feeds SET paused = :p, consecutive_failures = 0 "
                   "WHERE id = :i"), {"p": paused, "i": feed_id})
    db.commit()
    return jsonify(_feed_row(_one(db, feed_id)))


@bp.post("/feeds/<int:feed_id>/pause")
@api_admin
def pause_feed(feed_id: int):
    return _set_paused(feed_id, True)


@bp.post("/feeds/<int:feed_id>/resume")
@api_admin
def resume_feed(feed_id: int):
    # Resuming clears the failure count, so a feed that recovered is not one
    # bad poll away from auto-pausing again.
    return _set_paused(feed_id, False)


@bp.post("/feeds/<int:feed_id>/threshold")
@api_admin
def set_threshold(feed_id: int):
    db = get_db()
    if _one(db, feed_id) is None:
        return error("No such feed.", 404)
    raw = (request.get_json(silent=True) or {}).get("threshold")
    try:
        value = None if raw in (None, "") else float(raw)
    except (TypeError, ValueError):
        return error("threshold must be a number between 0 and 1, or null.", 400)
    if value is not None and not 0.0 <= value <= 1.0:
        return error("threshold must be between 0 and 1.", 400)
    db.execute(sql("UPDATE feeds SET score_threshold = :t WHERE id = :i"),
               {"t": value, "i": feed_id})
    db.commit()
    return jsonify(_feed_row(_one(db, feed_id)))


@bp.post("/feeds/<int:feed_id>/tags")
@api_admin
def set_tags(feed_id: int):
    """Tags group the sidebar. Normalised the way the form does it, so the two
    front ends cannot produce different tags from the same typing."""
    db = get_db()
    if _one(db, feed_id) is None:
        return error("No such feed.", 404)
    raw = (request.get_json(silent=True) or {}).get("tags", "")
    if isinstance(raw, list):
        raw = ",".join(str(t) for t in raw)
    normalised = tag_util.normalize(raw)
    db.execute(sql("UPDATE feeds SET tags = :t WHERE id = :i"),
               {"t": normalised or None, "i": feed_id})
    db.commit()
    return jsonify(_feed_row(_one(db, feed_id)))


@bp.get("/feeds/opml")
@api_auth
def export_opml():
    """OPML out. Like the Markdown export, this cannot be a plain link in a
    bearer client, so the filename travels in Content-Disposition."""
    db = get_db()
    body = opml.document(_all_feeds(db))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        body, mimetype="text/x-opml",
        headers={"Content-Disposition":
                 f'attachment; filename="betternews-feeds-{stamp}.opml"'},
    )


@bp.post("/feeds/opml")
@api_admin
def import_opml():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return error("Attach an OPML file as `file`.", 400)
    try:
        added = opml.import_urls(get_db(), opml.urls_from(upload.read()))
    except ValueError as exc:
        return error(str(exc), 400)
    return jsonify({"added": added})

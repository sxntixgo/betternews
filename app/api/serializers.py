"""Rows to JSON, through the presenter layer.

Never serialize a raw row. `presenters.row_to_article` is what decides which
headline the reader sees once de-clickbait is on and what the reading time is;
skipping it puts the phone and the browser a month away from disagreeing.
"""

from app import presenters


def _iso(value):
    return value.isoformat() if value else None


def article(row, declickbait: bool) -> dict:
    """One article, as a list entry."""
    d = presenters.row_to_article(row, declickbait)
    return {
        "id": d["id"],
        "url": d["url"],
        "title": d["display_title"],
        # The original is only present when de-clickbait actually rewrote it, so
        # a client can show "Originally: …" exactly when the web UI does.
        "original_title": d.get("original_title"),
        "summary": d.get("summary"),
        "score": d.get("score"),
        "score_reason": d.get("score_reason"),
        # A boolean, not `articles.status`. The pipeline lifecycle is the
        # server's business; what a client needs to know is whether this was
        # filtered out for scoring low, so it can say so next to the reason.
        "hidden": d.get("status") == "hidden",
        "topics": list(d.get("topics") or []),
        "feed_id": d.get("feed_id"),
        "thumbnail_url": d.get("thumbnail_url"),
        "reading_time": d.get("reading_time"),
        "published_at": _iso(d.get("published_at")),
        "duplicate_count": d.get("duplicate_count", 0),
        "state": {
            "read": bool(d.get("read_at")),
            "saved": bool(d.get("saved_at")),
            "dismissed": bool(d.get("dismissed_at")),
            "opinion": d.get("opinion"),
        },
    }


def article_detail(row, blocks, aside_count: int, declickbait: bool) -> dict:
    """One article with its body, already split into blocks.

    The blocks carry the padding classification the reader configured, so a
    client renders the same folded rails as the web reader instead of
    reimplementing `content_filter`.
    """
    out = article(row, declickbait)
    out["blocks"] = blocks
    out["aside_count"] = aside_count
    return out


def feed(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "unread": row["unread"] or 0,
        "hidden": row["hidden"] or 0,
        "saved": row["saved"] or 0,
        "paused": bool(row["paused"]),
        "tags": list(row["tags"] or []),
    }

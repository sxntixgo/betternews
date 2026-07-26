#!/usr/bin/env python3
"""One-shot import of the legacy SQLite database into Postgres.

    python scripts/import_sqlite.py --sqlite data/rss.db [--dry-run]

Re-runnable: it refuses to touch a non-empty Postgres unless --force is given,
so a half-finished run can be retried from a clean slate rather than doubling
rows.

The SQLite file is never written to. It stays on disk as the rollback.

Conversions:
  * ISO-8601 text timestamps -> aware datetimes
  * 0/1 integers             -> booleans
  * articles.status liked/disliked/dismissed -> user_article_state, since
    status is now the pipeline lifecycle only
  * articles.read_at / saved_at              -> user_article_state
  * votes                    -> user-scoped, with title/summary snapshots taken
                                from the article while it still exists
  * every ingested (feed_id, guid) -> seen_guids, so retention-pruned articles
                                are not re-ingested later
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, insert, select, text  # noqa: E402

from app.db import get_engine, init_db  # noqa: E402
from app.models import (  # noqa: E402
    articles, feeds, preferences, seen_guids, settings, user_article_state,
    users, votes,
)

BATCH = 1000


def _dt(value):
    """Parse the stored 'YYYY-MM-DDTHH:MM:SSZ' form into an aware datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _bool(value):
    return bool(value) if value is not None else None


def _jsonb(value):
    """aside_spans was TEXT holding JSON; hand Postgres a real object."""
    if not value:
        return None
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def _rows(src, table):
    cur = src.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    for row in cur:
        yield dict(zip(cols, row))


def _has(src, table) -> bool:
    return src.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _chunk(seq, n=BATCH):
    buf = []
    for item in seq:
        buf.append(item)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default=os.environ.get("LEGACY_DB", "data/rss.db"))
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be imported, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="import even though Postgres already has articles")
    args = ap.parse_args()

    if not os.path.exists(args.sqlite):
        print(f"error: {args.sqlite} not found", file=sys.stderr)
        return 2

    src = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    init_db()
    engine = get_engine()
    with engine.begin() as db:
        existing = db.execute(select(func.count()).select_from(articles)).scalar_one()
        if existing and not args.force:
            print(f"error: Postgres already holds {existing} articles. "
                  f"Re-run with --force to import anyway, or drop the database "
                  f"first for a clean retry.", file=sys.stderr)
            return 3

        owner = db.execute(select(users.c.id).order_by(users.c.id).limit(1)).scalar()
        if owner is None and not args.dry_run:
            owner = db.execute(
                insert(users).values(username="owner", password_hash="", role="admin")
                .returning(users.c.id)
            ).scalar_one()

        counts = {}

        # ── feeds ────────────────────────────────────────────────────────────
        feed_rows = [{
            "id": r["id"], "url": r["url"], "title": r["title"],
            "last_polled_at": _dt(r.get("last_polled_at")),
            "last_success_at": _dt(r.get("last_success_at")),
            "last_error": r.get("last_error"),
            "consecutive_failures": r.get("consecutive_failures") or 0,
            "paused": _bool(r.get("paused")) or False,
            "score_threshold": r.get("score_threshold"),
            "etag": r.get("etag"), "last_modified": r.get("last_modified"),
            "tags": r.get("tags"),
        } for r in _rows(src, "feeds")]
        counts["feeds"] = len(feed_rows)
        if feed_rows and not args.dry_run:
            db.execute(insert(feeds), feed_rows)

        # ── articles (+ per-user state carved out of status/read_at/saved_at) ─
        art_rows, state_rows, guid_rows = [], [], []
        for r in _rows(src, "articles"):
            status = r.get("status") or "new"
            opinion, dismissed = None, None
            if status in ("liked", "disliked"):
                opinion, status = status, "summarized"
            elif status == "dismissed":
                dismissed, status = _dt(r.get("created_at")) or datetime.now(timezone.utc), "summarized"
            if status not in ("new", "scored", "hidden", "summarized"):
                status = "new"

            art_rows.append({
                "id": r["id"], "feed_id": r["feed_id"], "guid": r["guid"],
                "url": r["url"], "title": r["title"],
                "published_at": _dt(r.get("published_at")),
                "raw_snippet": r.get("raw_snippet"),
                "feed_content": r.get("feed_content"),
                "full_text": r.get("full_text"), "summary": r.get("summary"),
                "clean_title": r.get("clean_title"),
                "title_was_clickbait": _bool(r.get("title_was_clickbait")),
                "aside_spans": _jsonb(r.get("aside_spans")),
                "score": r.get("score"), "score_reason": r.get("score_reason"),
                "thumbnail_url": r.get("thumbnail_url"), "status": status,
                "created_at": _dt(r.get("created_at")) or datetime.now(timezone.utc),
            })
            guid_rows.append({"feed_id": r["feed_id"], "guid": r["guid"]})

            read_at, saved_at = _dt(r.get("read_at")), _dt(r.get("saved_at"))
            if read_at or saved_at or opinion or dismissed:
                state_rows.append({
                    "user_id": owner, "article_id": r["id"],
                    "read_at": read_at, "saved_at": saved_at,
                    "dismissed_at": dismissed, "opinion": opinion,
                })
        counts["articles"] = len(art_rows)
        counts["user_article_state"] = len(state_rows)
        counts["seen_guids"] = len(guid_rows)

        if not args.dry_run:
            for chunk in _chunk(art_rows):
                db.execute(insert(articles), chunk)
            for chunk in _chunk(guid_rows):
                db.execute(
                    text("INSERT INTO seen_guids (feed_id, guid) VALUES (:feed_id, :guid) "
                         "ON CONFLICT DO NOTHING"), chunk)
            for chunk in _chunk(state_rows):
                db.execute(insert(user_article_state), chunk)

        # ── votes: snapshot the article now, so retention can prune it later ─
        titles = {r["id"]: (r.get("title"), r.get("summary"))
                  for r in _rows(src, "articles")}
        vote_rows = []
        for r in _rows(src, "votes"):
            t, sm = titles.get(r["article_id"], (None, None))
            vote_rows.append({
                "id": r["id"], "user_id": owner, "article_id": r["article_id"],
                "value": r["value"], "title_snapshot": t, "summary_snapshot": sm,
                "created_at": _dt(r.get("created_at")) or datetime.now(timezone.utc),
            })
        counts["votes"] = len(vote_rows)
        if vote_rows and not args.dry_run:
            db.execute(insert(votes), vote_rows)

        # ── singletons ───────────────────────────────────────────────────────
        pref = next(_rows(src, "preferences"), None)
        if pref and not args.dry_run:
            db.execute(text(
                "INSERT INTO preferences (id, profile_text, updated_at) "
                "VALUES (1, :t, :u) ON CONFLICT (id) DO UPDATE "
                "SET profile_text = EXCLUDED.profile_text"),
                {"t": pref.get("profile_text") or "",
                 "u": _dt(pref.get("updated_at")) or datetime.now(timezone.utc)})
        counts["preferences"] = 1 if pref else 0

        set_rows = list(_rows(src, "settings")) if _has(src, "settings") else []
        counts["settings"] = len(set_rows)
        if set_rows and not args.dry_run:
            for r in set_rows:
                db.execute(text(
                    "INSERT INTO settings (key, value) VALUES (:k, :v) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"),
                    {"k": r["key"], "v": r["value"]})

        # Identity sequences must be advanced past the ids we forced in, or the
        # next insert collides on a duplicate key. Classic post-migration bug.
        if not args.dry_run:
            for tbl in ("feeds", "articles", "votes", "users"):
                db.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {tbl}), 1))"))

    src.close()
    label = "would import" if args.dry_run else "imported"
    for k in ("feeds", "articles", "user_article_state", "seen_guids",
              "votes", "preferences", "settings"):
        print(f"{label} {counts.get(k, 0):>7} {k}")
    if args.dry_run:
        print("\ndry run — nothing written")
    else:
        print("\nKeep the SQLite file: it is the rollback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Retention: prune old articles, and bulk-clear read articles per user.

**Scope guarantee — this touches `articles` and per-user state, nothing else.**
Feeds, settings, preferences, votes and users are never deleted here. See the
table in `docs/feature-plan.md` 0.9e, and `test_retention.py`, which seeds every
table, prunes with a zero-day window, and asserts only `articles` shrank.

Two protections make the deletion safe:

* Favorited articles are never pruned (0.9c).
* `votes` carries `title_snapshot`/`summary_snapshot` and `ON DELETE SET NULL`,
  so deleting an article costs the preference profile nothing (0.9d). Without
  that, pruning would silently erase training signal through the FK cascade.

Deleting an article leaves its `seen_guids` tombstone behind, so the next poll
does not re-ingest what was just reclaimed.
"""

import logging

from sqlalchemy import and_, func, select, text

from app.db import get_setting, set_setting
from app.models import articles as A
from app.models import user_article_state as S

log = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 15
BATCH = 1000

SETTING_DAYS = "retention_days"
SETTING_CONFIRMED = "retention_confirmed"


def retention_days(db) -> int:
    """0 disables pruning entirely."""
    raw = get_setting(db, SETTING_DAYS, str(DEFAULT_RETENTION_DAYS))
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS


def is_confirmed(db) -> bool:
    """Pruning stays inert until explicitly confirmed.

    The default window is shorter than the age of most existing corpora, so the
    first run would otherwise delete nearly everything the moment the feature
    shipped.
    """
    return get_setting(db, SETTING_CONFIRMED, "") == "1"


def set_confirmed(db, value: bool) -> None:
    set_setting(db, SETTING_CONFIRMED, "1" if value else "")


def _prunable(days: int):
    """Articles past the window that no user has favorited.

    Keyed on `created_at` (when we ingested it), never `published_at`: feeds
    routinely carry wrong or future publication dates, and retention driven by
    publisher metadata would hoard junk and delete good articles early.
    """
    cutoff = func.now() - text(f"INTERVAL '{int(days)} days'")
    saved = (
        select(S.c.article_id)
        .where(and_(S.c.article_id == A.c.id, S.c.saved_at.isnot(None)))
    )
    return select(A.c.id).where(A.c.created_at < cutoff).where(~saved.exists())


def preview(db, days: int | None = None) -> dict:
    """Counts for the dry run. Writes nothing."""
    days = retention_days(db) if days is None else days
    if days <= 0:
        return {"days": 0, "articles": 0, "total": _total(db), "saved": _saved(db)}
    n = db.execute(
        select(func.count()).select_from(_prunable(days).subquery())
    ).scalar_one()
    return {"days": days, "articles": n, "total": _total(db), "saved": _saved(db)}


def _total(db) -> int:
    return db.execute(select(func.count()).select_from(A)).scalar_one()


def _saved(db) -> int:
    return db.execute(
        select(func.count(func.distinct(S.c.article_id))).where(S.c.saved_at.isnot(None))
    ).scalar_one()


def prune(db, days: int | None = None) -> int:
    """Delete articles past the window. Returns how many went.

    Batched: one 17k-row DELETE with FK cascades and a GIN index to maintain
    holds a long lock.
    """
    days = retention_days(db) if days is None else days
    if days <= 0:
        return 0
    removed = 0
    while True:
        ids = [r[0] for r in db.execute(_prunable(days).limit(BATCH)).all()]
        if not ids:
            break
        db.execute(A.delete().where(A.c.id.in_(ids)))
        db.commit()
        removed += len(ids)
    if removed:
        log.info("Retention: pruned %d articles older than %d days", removed, days)
    return removed


def run(app) -> int:
    """Scheduled entry point. Inert until confirmed in Settings."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        try:
            if not is_confirmed(db):
                log.info("Retention not confirmed — skipping")
                return 0
            return prune(db)
        finally:
            db.close()


def clear_read(db, user_ids: list[int]) -> int:
    """Bulk-remove read articles from the given users' lists.

    Clears *per-user state only*. Article rows are shared, so deleting one
    because user A read it would remove it from user B's list — who may never
    have seen it. Rows nobody references any more are reclaimed by `prune`.

    Favorited articles are kept: starring something and then reading it must not
    make it disappear.
    """
    if not user_ids:
        return 0
    res = db.execute(
        S.delete()
        .where(S.c.user_id.in_(user_ids))
        .where(S.c.read_at.isnot(None))
        .where(S.c.saved_at.is_(None))
    )
    log.info("Cleared %d read entries for users %s", res.rowcount, user_ids)
    return res.rowcount


def clear_read_preview(db, user_ids: list[int]) -> int:
    if not user_ids:
        return 0
    return db.execute(
        select(func.count())
        .select_from(S)
        .where(S.c.user_id.in_(user_ids))
        .where(S.c.read_at.isnot(None))
        .where(S.c.saved_at.is_(None))
    ).scalar_one()

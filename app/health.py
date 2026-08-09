"""Ingestion health: auto-recovery for paused feeds, and a truthful healthcheck.

A transient DNS failure in June auto-paused every feed on this install, and
nothing ever retried — a momentary fault became 43 days of silence while the
container reported "healthy" because the healthcheck only pinged Flask.

Both halves of that are fixed here: paused feeds are re-probed on a widening
backoff, and health is judged on whether anything is actually being ingested.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.models import feeds as F

log = logging.getLogger(__name__)

# Re-probe schedule after auto-pause, by consecutive-failure count. A feed that
# keeps failing is retried ever more slowly rather than hammered or abandoned.
RETRY_BACKOFF_HOURS = (1, 4, 12, 24)
MAX_BACKOFF_HOURS = 24

# Ingestion is considered stalled after this long with no successful poll.
STALE_AFTER_HOURS = 6


def _backoff_hours(failures: int) -> int:
    over = max(0, failures - 5)          # AUTO_PAUSE_AFTER_FAILURES
    idx = min(over, len(RETRY_BACKOFF_HOURS) - 1)
    return min(RETRY_BACKOFF_HOURS[idx], MAX_BACKOFF_HOURS)


def due_for_retry(db):
    """Paused feeds whose backoff has elapsed."""
    rows = db.execute(
        select(F.c.id, F.c.url, F.c.consecutive_failures, F.c.last_polled_at)
        .where(F.c.paused)
    ).mappings().all()
    now = datetime.now(timezone.utc)
    due = []
    for r in rows:
        last = r["last_polled_at"]
        if last is None:
            due.append(r)
            continue
        if last <= now - timedelta(hours=_backoff_hours(r["consecutive_failures"])):
            due.append(r)
    return due


def retry_paused_feeds(app) -> int:
    """Re-probe paused feeds; a success clears the pause. Returns how many recovered.

    Auto-pause without auto-recovery is a trap: it protects the pipeline from a
    dead feed but makes a *transient* failure permanent.
    """
    from app.db import get_db_direct
    from app.feeds import _poll_feed

    recovered = 0
    with app.app_context():
        db = get_db_direct()
        try:
            for feed in due_for_retry(db):
                log.info("Retrying paused feed id=%d (%s)", feed["id"], feed["url"])
                # Unpause for the attempt; a failure re-pauses via _record_failure.
                db.execute(text("UPDATE feeds SET paused=false WHERE id=:i"),
                           {"i": feed["id"]})
                db.commit()
                _poll_feed(db, feed["id"], feed["url"])
                still = db.execute(
                    select(F.c.paused).where(F.c.id == feed["id"])
                ).scalar()
                if not still:
                    recovered += 1
                    log.info("Feed id=%d recovered", feed["id"])
            return recovered
        finally:
            db.close()


def ingestion_status(db) -> dict:
    """Is anything actually arriving?

    Three different questions, and they were not distinguishable before:

    - `paused` — feeds the app gave up on. Visible already.
    - `stale` — *nothing at all* has succeeded recently. This keys on
      ``MAX(last_success_at)`` across every feed, so one healthy feed hides
      every other feed being dead.
    - `stale_feeds` — feeds that are not paused and yet have not succeeded
      inside the window. This is the one that was missing, and it is the exact
      shape of the failure this module was written for: a fault that is silent
      because *something* is still arriving. On a two-feed install one dead
      feed is half the news, and `paused < total` still reported "ok".

    `healthy` deliberately does **not** fold in `stale_feeds`. This backs a
    container healthcheck, and one broken feed is not a reason to mark the whole
    app unhealthy and invite a restart loop that cannot fix it. It is reported
    so a person can see it, not so Docker can act on it.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS)
    row = db.execute(text("""
        SELECT COUNT(*)                                        AS total,
               COUNT(*) FILTER (WHERE paused)                  AS paused,
               COUNT(*) FILTER (WHERE NOT paused
                                  AND (last_success_at IS NULL
                                       OR last_success_at < :cutoff))
                                                               AS stale_feeds,
               MAX(last_success_at)                            AS last_success
        FROM feeds
    """), {"cutoff": cutoff}).mappings().first()
    total = row["total"] or 0
    paused = row["paused"] or 0
    stale_feeds = row["stale_feeds"] or 0
    last = row["last_success"]
    stale = bool(total and (last is None or last < cutoff))
    return {
        "total": total,
        "paused": paused,
        "active": total - paused,
        "stale_feeds": stale_feeds,
        "last_success_at": last,
        "stale": stale,
        # No feeds at all is a fresh install, not a fault.
        "healthy": total == 0 or (not stale and paused < total),
    }

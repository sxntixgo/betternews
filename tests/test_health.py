"""Feed auto-recovery and the ingestion-aware healthcheck.

Regression cover for the June outage: a transient DNS failure paused every feed,
nothing retried, and the container reported healthy for 43 days.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app import health
from tests.conftest import add_feed


def _pause(db, fid, failures=5, last_polled=None):
    db.execute(text(
        "UPDATE feeds SET paused=true, consecutive_failures=:f, last_polled_at=:t "
        "WHERE id=:i"),
        {"f": failures, "t": last_polled, "i": fid})
    db.commit()


def _ok_parse():
    p = MagicMock()
    p.bozo = False
    p.status = 200
    p.feed = {"title": "F"}
    p.entries = []
    # MagicMock invents attributes on access, so an unset etag/modified would
    # be a Mock object written into a TEXT column.
    p.etag = None
    p.modified = None
    return p


# ── backoff ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("failures,expected", [
    (5, 1), (6, 4), (7, 12), (8, 24), (50, 24),
])
def test_backoff_widens_then_caps(failures, expected):
    assert health._backoff_hours(failures) == expected


def test_feed_paused_long_ago_is_due(db_conn):
    fid = add_feed(db_conn)
    _pause(db_conn, fid, last_polled=datetime.now(timezone.utc) - timedelta(hours=48))
    assert [f["id"] for f in health.due_for_retry(db_conn)] == [fid]


def test_feed_paused_moments_ago_is_not_due(db_conn):
    fid = add_feed(db_conn)
    _pause(db_conn, fid, last_polled=datetime.now(timezone.utc) - timedelta(minutes=5))
    assert health.due_for_retry(db_conn) == []


def test_feed_never_polled_is_due(db_conn):
    fid = add_feed(db_conn)
    _pause(db_conn, fid, last_polled=None)
    assert [f["id"] for f in health.due_for_retry(db_conn)] == [fid]


def test_active_feeds_are_not_candidates(db_conn):
    add_feed(db_conn)
    assert health.due_for_retry(db_conn) == []


# ── recovery ───────────────────────────────────────────────────────────────────

def test_a_working_feed_is_unpaused(db_conn, app):
    """The June scenario: the fault was transient, so the retry should stick."""
    fid = add_feed(db_conn, url="https://ok.test/rss")
    _pause(db_conn, fid, last_polled=datetime.now(timezone.utc) - timedelta(hours=48))
    with patch("app.feeds.feedparser.parse", return_value=_ok_parse()):
        assert health.retry_paused_feeds(app) == 1
    row = db_conn.execute(text(
        "SELECT paused, consecutive_failures FROM feeds WHERE id=:i"), {"i": fid}
    ).mappings().first()
    assert row["paused"] is False
    assert row["consecutive_failures"] == 0


def test_a_still_broken_feed_stays_paused(db_conn, app):
    fid = add_feed(db_conn, url="https://bad.test/rss")
    _pause(db_conn, fid, last_polled=datetime.now(timezone.utc) - timedelta(hours=48))
    with patch("app.feeds.feedparser.parse", side_effect=OSError("still down")):
        assert health.retry_paused_feeds(app) == 0
    assert db_conn.execute(text(
        "SELECT paused FROM feeds WHERE id=:i"), {"i": fid}).scalar() is True


def test_retry_skips_feeds_inside_their_backoff(db_conn, app):
    fid = add_feed(db_conn)
    _pause(db_conn, fid, last_polled=datetime.now(timezone.utc) - timedelta(minutes=1))
    with patch("app.feeds.feedparser.parse") as parse:
        assert health.retry_paused_feeds(app) == 0
        parse.assert_not_called()


def test_retry_is_a_noop_with_nothing_paused(app):
    assert health.retry_paused_feeds(app) == 0


# ── ingestion status ───────────────────────────────────────────────────────────

def test_fresh_install_is_healthy(db_conn):
    st = health.ingestion_status(db_conn)
    assert st["total"] == 0 and st["healthy"] is True


def test_recent_success_is_healthy(db_conn):
    fid = add_feed(db_conn)
    db_conn.execute(text("UPDATE feeds SET last_success_at=now() WHERE id=:i"), {"i": fid})
    db_conn.commit()
    st = health.ingestion_status(db_conn)
    assert st["healthy"] is True and st["stale"] is False


def test_old_success_is_stale(db_conn):
    """The exact shape of the outage: feeds present, nothing arriving."""
    fid = add_feed(db_conn)
    db_conn.execute(text(
        "UPDATE feeds SET last_success_at=now() - interval '43 days' WHERE id=:i"),
        {"i": fid})
    db_conn.commit()
    st = health.ingestion_status(db_conn)
    assert st["stale"] is True and st["healthy"] is False


def test_all_feeds_paused_is_unhealthy(db_conn):
    fid = add_feed(db_conn)
    db_conn.execute(text(
        "UPDATE feeds SET paused=true, last_success_at=now() WHERE id=:i"), {"i": fid})
    db_conn.commit()
    assert health.ingestion_status(db_conn)["healthy"] is False


def test_some_paused_is_still_healthy(db_conn):
    a = add_feed(db_conn, url="https://a.test/f")
    add_feed(db_conn, url="https://b.test/f")
    db_conn.execute(text("UPDATE feeds SET last_success_at=now()"))
    db_conn.execute(text("UPDATE feeds SET paused=true WHERE id=:i"), {"i": a})
    db_conn.commit()
    assert health.ingestion_status(db_conn)["healthy"] is True


# ── endpoint ───────────────────────────────────────────────────────────────────

def test_health_endpoint_is_public(anon_client):
    """The container healthcheck has no session."""
    assert anon_client.get("/health").status_code == 200


def test_health_reports_ok_when_ingesting(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        db.execute(text("UPDATE feeds SET last_success_at=now() WHERE id=:i"), {"i": fid})
        db.commit()
        db.close()
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json["status"] == "ok"


def test_health_returns_503_when_ingestion_stalled(client, app):
    """A container answering HTTP while ingesting nothing is not healthy."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        db.execute(text(
            "UPDATE feeds SET last_success_at=now() - interval '43 days' WHERE id=:i"),
            {"i": fid})
        db.commit()
        db.close()
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json["status"] == "degraded"
    assert r.json["ingestion_stale"] is True


def test_health_counts_paused_feeds(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        db.execute(text("UPDATE feeds SET paused=true WHERE id=:i"), {"i": fid})
        db.commit()
        db.close()
    assert client.get("/health").json["feeds_paused"] == 1


def test_retry_job_is_scheduled(app):
    from app.scheduler import init_scheduler
    assert "retry_paused" in {j.id for j in init_scheduler(app).get_jobs()}

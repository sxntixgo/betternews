"""Retention: pruning, bulk clear-read, and the scope guarantee.

The scope test is the important one — it encodes the invariant that retention
touches articles and nothing else, and will catch any future join or cascade
that quietly widens the blast radius.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app import retention
from tests.conftest import add_article, add_feed, add_user


def _old(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _uid(db):
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db)
    db.commit()
    return uid


# ── settings ───────────────────────────────────────────────────────────────────

def test_default_window_is_15_days(db_conn):
    assert retention.retention_days(db_conn) == retention.DEFAULT_RETENTION_DAYS == 15


def test_window_reads_the_setting(db_conn):
    from app.db import set_setting
    set_setting(db_conn, retention.SETTING_DAYS, "30")
    assert retention.retention_days(db_conn) == 30


@pytest.mark.parametrize("raw", ["", "abc", "-5", None])
def test_bad_window_falls_back_safely(db_conn, raw):
    from app.db import set_setting
    if raw is not None:
        set_setting(db_conn, retention.SETTING_DAYS, raw)
    days = retention.retention_days(db_conn)
    assert days >= 0


def test_pruning_is_inert_until_confirmed(db_conn, app):
    fid = add_feed(db_conn)
    add_article(db_conn, fid, created_at=_old(90))
    assert retention.is_confirmed(db_conn) is False
    assert retention.run(app) == 0
    assert db_conn.execute(text("SELECT COUNT(*) FROM articles")).scalar() == 1


def test_confirmed_run_prunes(db_conn, app):
    fid = add_feed(db_conn)
    add_article(db_conn, fid, created_at=_old(90))
    retention.set_confirmed(db_conn, True)
    db_conn.commit()
    assert retention.run(app) == 1


def test_zero_days_disables_pruning(db_conn):
    fid = add_feed(db_conn)
    add_article(db_conn, fid, created_at=_old(999))
    assert retention.prune(db_conn, days=0) == 0


# ── what gets pruned ───────────────────────────────────────────────────────────

def test_prunes_only_articles_past_the_window(db_conn):
    fid = add_feed(db_conn)
    old = add_article(db_conn, fid, seq=1, guid="old", created_at=_old(60))
    new = add_article(db_conn, fid, seq=2, guid="new", created_at=_old(1))
    assert retention.prune(db_conn, days=15) == 1
    ids = {r[0] for r in db_conn.execute(text("SELECT id FROM articles")).all()}
    assert ids == {new}
    assert old not in ids


def test_favorites_are_never_pruned(db_conn):
    """0.9c — starring an article protects it regardless of age."""
    from app.repo.articles import toggle_saved
    fid = add_feed(db_conn)
    saved = add_article(db_conn, fid, seq=1, guid="s", created_at=_old(365))
    add_article(db_conn, fid, seq=2, guid="u", created_at=_old(365))
    toggle_saved(db_conn, _uid(db_conn), saved)
    db_conn.commit()
    assert retention.prune(db_conn, days=15) == 1
    remaining = {r[0] for r in db_conn.execute(text("SELECT id FROM articles")).all()}
    assert remaining == {saved}


def test_pruning_keys_on_ingest_not_publication(db_conn):
    """Feeds carry wrong and future published_at values; created_at is ours."""
    fid = add_feed(db_conn)
    a = add_article(db_conn, fid, created_at=_old(1),
                    published_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert retention.prune(db_conn, days=15) == 0
    assert db_conn.execute(text("SELECT COUNT(*) FROM articles")).scalar() == 1


def test_pruning_is_batched_over_many_rows(db_conn):
    fid = add_feed(db_conn)
    for i in range(25):
        add_article(db_conn, fid, seq=i, guid=f"g{i}", created_at=_old(90))
    monkey = retention.BATCH
    retention.BATCH = 10          # force multiple passes
    try:
        assert retention.prune(db_conn, days=15) == 25
    finally:
        retention.BATCH = monkey
    assert db_conn.execute(text("SELECT COUNT(*) FROM articles")).scalar() == 0


# ── the profile must survive pruning (0.9d) ────────────────────────────────────

def test_pruning_keeps_votes_and_their_snapshots(db_conn):
    from app.repo.articles import record_vote
    fid = add_feed(db_conn)
    aid = add_article(db_conn, fid, title="Judged", summary="Body.",
                      created_at=_old(90))
    record_vote(db_conn, _uid(db_conn), aid, 1)
    db_conn.commit()

    assert retention.prune(db_conn, days=15) == 1

    row = db_conn.execute(text(
        "SELECT article_id, value, title_snapshot, summary_snapshot FROM votes"
    )).mappings().first()
    assert row is not None                    # cascade did NOT take it
    assert row["article_id"] is None          # pointer nulled, record intact
    assert row["title_snapshot"] == "Judged"
    assert row["summary_snapshot"] == "Body."


def test_profile_regeneration_works_after_everything_is_pruned(db_conn, app):
    """The whole point of 0.9d: an empty articles table still trains a profile."""
    from unittest.mock import patch
    from app.pipeline import regenerate_preferences
    from app.repo.articles import record_vote

    fid = add_feed(db_conn)
    aid = add_article(db_conn, fid, title="Kept in the vote", created_at=_old(90))
    record_vote(db_conn, _uid(db_conn), aid, 1)
    db_conn.commit()
    retention.prune(db_conn, days=15)
    assert db_conn.execute(text("SELECT COUNT(*) FROM articles")).scalar() == 0

    with patch("app.pipeline.ollama_client.generate") as gen:
        gen.return_value = "A profile."
        regenerate_preferences(app)
        prompt = gen.call_args.kwargs["prompt"]
    assert "Kept in the vote" in prompt        # trained from the snapshot


# ── tombstones (0.9e) ──────────────────────────────────────────────────────────

def test_pruned_articles_are_not_re_ingested(db_conn):
    """UNIQUE(feed_id, guid) can't help — it died with the row."""
    from app.feeds import _poll_feed
    from unittest.mock import MagicMock, patch

    fid = add_feed(db_conn, url="https://ex.com/f")
    db_conn.execute(text(
        "INSERT INTO seen_guids (feed_id, guid) VALUES (:f, 'ghost')"), {"f": fid})
    db_conn.commit()

    parsed = MagicMock()
    parsed.bozo = False
    parsed.status = 200
    parsed.feed = {"title": "F"}
    parsed.entries = [{"id": "ghost", "link": "https://ex.com/a", "title": "Back?",
                       "summary": "s"}]
    with patch("app.feeds.feedparser.parse", return_value=parsed):
        _poll_feed(db_conn, fid, "https://ex.com/f")

    assert db_conn.execute(text("SELECT COUNT(*) FROM articles")).scalar() == 0


# ── scope guarantee (0.9e) ★ ───────────────────────────────────────────────────

def test_retention_touches_articles_and_nothing_else(db_conn):
    """Seed every table, prune everything, assert only `articles` shrank.

    This encodes the whole invariant. If a future join or cascade widens the
    blast radius, this fails.
    """
    from app.db import set_setting

    uid = _uid(db_conn)
    fid = add_feed(db_conn, url="https://scope.test/f")
    aid = add_article(db_conn, fid, created_at=_old(90))
    from app.repo.articles import record_vote, mark_read
    record_vote(db_conn, uid, aid, 1)
    mark_read(db_conn, uid, aid)
    set_setting(db_conn, "some_key", "some_value")
    db_conn.execute(text(
        "INSERT INTO preferences (user_id, profile_text) "
        "SELECT id, 'profile' FROM users ORDER BY id LIMIT 1 "
        "ON CONFLICT (user_id) DO UPDATE SET profile_text='profile'"))
    # The fixture inserts directly rather than via poll, so seed the tombstone.
    db_conn.execute(text(
        "INSERT INTO seen_guids (feed_id, guid) VALUES (:f, 'seeded')"), {"f": fid})
    db_conn.commit()

    tables = ["feeds", "settings", "preferences", "votes", "users", "seen_guids"]
    before = {t: db_conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
              for t in tables}
    assert all(v > 0 for v in before.values()), before

    removed = retention.prune(db_conn, days=15)
    assert removed == 1

    after = {t: db_conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
             for t in tables}
    assert after == before, f"retention altered {set(before) - set(after)}: {before} -> {after}"
    assert db_conn.execute(text("SELECT COUNT(*) FROM articles")).scalar() == 0


# ── preview ────────────────────────────────────────────────────────────────────

def test_preview_reports_without_deleting(db_conn):
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="a", created_at=_old(90))
    add_article(db_conn, fid, seq=2, guid="b", created_at=_old(1))
    p = retention.preview(db_conn, days=15)
    assert p == {"days": 15, "articles": 1, "total": 2, "saved": 0}
    assert db_conn.execute(text("SELECT COUNT(*) FROM articles")).scalar() == 2


def test_preview_when_disabled(db_conn):
    from app.db import set_setting
    set_setting(db_conn, retention.SETTING_DAYS, "0")
    assert retention.preview(db_conn)["days"] == 0


# ── bulk clear-read (0.9b) ─────────────────────────────────────────────────────

def test_clear_read_removes_only_read_entries(db_conn):
    from app.repo.articles import mark_read
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    read = add_article(db_conn, fid, seq=1, guid="r")
    add_article(db_conn, fid, seq=2, guid="u")
    mark_read(db_conn, uid, read)
    db_conn.commit()

    assert retention.clear_read(db_conn, [uid]) == 1
    db_conn.commit()
    assert db_conn.execute(text("SELECT COUNT(*) FROM user_article_state")).scalar() == 0
    # The shared article row survives.
    assert db_conn.execute(text("SELECT COUNT(*) FROM articles")).scalar() == 2


def test_clear_read_keeps_favorites(db_conn):
    from app.repo.articles import mark_read, toggle_saved
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    aid = add_article(db_conn, fid)
    mark_read(db_conn, uid, aid)
    toggle_saved(db_conn, uid, aid)
    db_conn.commit()
    assert retention.clear_read(db_conn, [uid]) == 0


def test_clear_read_is_scoped_to_the_named_users(db_conn):
    """One user's cleanup must not touch another's list."""
    from app.repo.articles import mark_read
    a = _uid(db_conn)
    b = add_user(db_conn, username="second", role="user")
    fid = add_feed(db_conn)
    aid = add_article(db_conn, fid)
    mark_read(db_conn, a, aid)
    mark_read(db_conn, b, aid)
    db_conn.commit()

    assert retention.clear_read(db_conn, [a]) == 1
    db_conn.commit()
    left = db_conn.execute(text(
        "SELECT user_id FROM user_article_state")).scalars().all()
    assert left == [b]


def test_clear_read_no_users_is_a_noop(db_conn):
    assert retention.clear_read(db_conn, []) == 0
    assert retention.clear_read_preview(db_conn, []) == 0


def test_clear_read_preview_counts_without_deleting(db_conn):
    from app.repo.articles import mark_read
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    mark_read(db_conn, uid, add_article(db_conn, fid))
    db_conn.commit()
    assert retention.clear_read_preview(db_conn, [uid]) == 1
    assert db_conn.execute(text("SELECT COUNT(*) FROM user_article_state")).scalar() == 1


# ── settings routes ────────────────────────────────────────────────────────────


# ── dismissed articles are visible, but retention still owns deletion ──────────

def test_retention_deletes_a_dismissed_article_past_the_window(db_conn):
    """Dismissing stopped removing articles, so this is now the only thing that
    does -- the deadline has to actually fire."""
    fid = add_feed(db_conn)
    add_article(db_conn, fid, status="dismissed", created_at=_old(60))
    assert retention.prune(db_conn, days=15) == 1


def test_a_starred_article_survives_even_when_dismissed(db_conn):
    """Starring is the one thing that beats the deadline."""
    fid = add_feed(db_conn)
    add_article(db_conn, fid, status="dismissed",
                saved_at=datetime.now(timezone.utc), created_at=_old(60))
    assert retention.prune(db_conn, days=15) == 0


def test_a_dismissed_article_inside_the_window_stays(db_conn):
    fid = add_feed(db_conn)
    add_article(db_conn, fid, status="dismissed", created_at=_old(2))
    assert retention.prune(db_conn, days=15) == 0

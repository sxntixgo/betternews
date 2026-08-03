"""Ranking accuracy measurement — the criterion docs/plan.md never checked."""

import pytest
from sqlalchemy import text

from app import insights
from tests.conftest import add_article, add_feed


def _voted(db, score, value, seq=1):
    from app.repo.articles import record_vote
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db)
    fid = db.execute(text("SELECT id FROM feeds LIMIT 1")).scalar() or add_feed(db)
    aid = add_article(db, fid, seq=seq, guid=f"g{seq}", score=score)
    record_vote(db, uid, aid, value)
    db.commit()
    return aid


def test_histogram_is_empty_without_scores(db_conn):
    assert all(b["n"] == 0 for b in insights.score_histogram(db_conn))


def test_histogram_buckets_scores(db_conn):
    fid = add_feed(db_conn)
    # 0.05 is exactly a bucket boundary, so use values clearly inside one.
    add_article(db_conn, fid, seq=1, guid="a", score=0.02)
    add_article(db_conn, fid, seq=2, guid="b", score=0.97)
    h = insights.score_histogram(db_conn)
    assert h[0]["n"] == 1 and h[-1]["n"] == 1


def test_perfect_score_lands_in_the_last_bucket(db_conn):
    """width_bucket puts 1.0 in an overflow bucket — it must not vanish."""
    add_article(db_conn, add_feed(db_conn), score=1.0)
    assert insights.score_histogram(db_conn)[-1]["n"] == 1


def test_agreement_with_no_votes(db_conn):
    a = insights.agreement(db_conn, 0.35)
    assert a["votes"] == 0 and a["rate"] is None


def test_agreement_counts_both_directions(db_conn):
    _voted(db_conn, 0.9, 1, seq=1)      # liked and scored high  → agrees
    _voted(db_conn, 0.1, -1, seq=2)     # disliked and scored low → agrees
    _voted(db_conn, 0.1, 1, seq=3)      # liked but would be hidden → disagrees
    a = insights.agreement(db_conn, 0.35)
    assert a["votes"] == 3 and a["agreed"] == 2 and a["rate"] == 67


def test_suggested_threshold_separates_the_votes(db_conn):
    for i in range(3):
        _voted(db_conn, 0.9, 1, seq=i)
    for i in range(3, 6):
        _voted(db_conn, 0.1, -1, seq=i)
    s = insights.suggest_threshold(db_conn)
    assert 0.15 <= s["threshold"] <= 0.9
    assert s["rate"] == 100


def test_no_suggestion_without_votes(db_conn):
    assert insights.suggest_threshold(db_conn) is None


def test_per_feed_surfaces_never_liked_feeds(db_conn):
    fid = add_feed(db_conn, url="https://never.test/f", title="Never Liked")
    add_article(db_conn, fid)
    rows = {r["feed"]: r for r in insights.per_feed(db_conn)}
    assert rows["Never Liked"]["likes"] == 0
    assert rows["Never Liked"]["articles"] == 1


def test_per_topic_needs_votes(db_conn):
    assert insights.per_topic(db_conn) == []


def test_per_topic_aggregates(db_conn):
    from app.repo.articles import record_vote
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db_conn)
    aid = add_article(db_conn, add_feed(db_conn), topics=["ai"])
    record_vote(db_conn, uid, aid, 1)
    db_conn.commit()
    assert insights.per_topic(db_conn)[0]["topic"] == "ai"


def test_pipeline_health_counts_by_status(db_conn):
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="a", status="new")
    add_article(db_conn, fid, seq=2, guid="b", status="hidden")
    p = insights.pipeline_health(db_conn)
    assert p["unscored"] == 1 and p["hidden"] == 1 and p["total"] == 2


# ── page + threshold tuning ────────────────────────────────────────────────────


def test_pipeline_honours_the_tuned_threshold(db_conn):
    """The point of A4: applying a suggestion changes what gets hidden."""
    from unittest.mock import patch
    from app.db import set_setting
    from app.pipeline import score_new_articles
    set_setting(db_conn, "score_threshold", "0.8")
    db_conn.commit()
    aid = add_article(db_conn, add_feed(db_conn), status="new", score=None)
    with patch("app.pipeline.ollama_client.generate",
               return_value={"score": 0.6, "reason": "r"}):
        score_new_articles(db_conn, "profile")
    assert db_conn.execute(text("SELECT status FROM articles WHERE id=:i"),
                           {"i": aid}).scalar() == "hidden"



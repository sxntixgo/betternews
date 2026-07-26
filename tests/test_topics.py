"""Topic tagging and the deterministic rules layered over the LLM score."""

import pytest
from sqlalchemy import text

from app import topics
from tests.conftest import add_article, add_feed


# ── normalisation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (["AI", "Formula 1"], ["ai", "formula-1"]),
    (["  Local Politics  "], ["local-politics"]),
    (["ai", "AI", "Ai"], ["ai"]),                 # deduped case-insensitively
    (["a  b", "c/d", "e_f"], ["a-b", "c-d", "e-f"]),
    ("single-string", ["single-string"]),
    ([], []), (None, []), ("", []),
    ({"not": "a list"}, []),
    (["", "   ", "---"], []),
])
def test_normalize(raw, expected):
    assert topics.normalize(raw) == expected


def test_normalize_caps_the_count():
    assert len(topics.normalize([f"t{i}" for i in range(20)])) == topics.MAX_TOPICS


def test_normalize_truncates_absurd_slugs():
    assert len(topics.normalize(["x" * 200])[0]) <= 40


# ── rules ──────────────────────────────────────────────────────────────────────

def test_no_rules_leaves_the_score_alone():
    assert topics.apply_rules(0.6, ["ai"], {}) == (0.6, False, None)


def test_muted_topic_hides_regardless_of_score():
    score, muted, note = topics.apply_rules(0.99, ["crypto"], {"crypto": {"muted": True}})
    assert muted is True
    assert "Muted topic: crypto" in note


def test_adjustments_sum_across_topics():
    rule_map = {"ai": {"adjustment": 0.2}, "hardware": {"adjustment": 0.1}}
    score, muted, note = topics.apply_rules(0.5, ["ai", "hardware"], rule_map)
    assert score == pytest.approx(0.8)
    assert muted is False and "+0.30" in note


def test_adjusted_scores_stay_in_range():
    assert topics.apply_rules(0.95, ["ai"], {"ai": {"adjustment": 0.5}})[0] == 1.0
    assert topics.apply_rules(0.05, ["ai"], {"ai": {"adjustment": -0.5}})[0] == 0.0


def test_mute_wins_over_a_boost_on_another_topic():
    rule_map = {"ai": {"adjustment": 0.5}, "crypto": {"muted": True}}
    _, muted, _ = topics.apply_rules(0.9, ["ai", "crypto"], rule_map)
    assert muted is True


# ── persistence ────────────────────────────────────────────────────────────────

def test_set_and_read_a_rule(db_conn):
    topics.set_rule(db_conn, "AI", adjustment=0.2)
    db_conn.commit()
    assert topics.rules(db_conn)["ai"]["adjustment"] == pytest.approx(0.2)


def test_set_rule_upserts(db_conn):
    topics.set_rule(db_conn, "ai", adjustment=0.2)
    topics.set_rule(db_conn, "ai", muted=True)
    db_conn.commit()
    assert topics.rules(db_conn)["ai"]["muted"] is True


def test_delete_rule(db_conn):
    topics.set_rule(db_conn, "ai", adjustment=0.2)
    topics.delete_rule(db_conn, "ai")
    db_conn.commit()
    assert "ai" not in topics.rules(db_conn)


@pytest.mark.parametrize("topic,adjustment", [("", 0.0), ("   ", 0.0), ("ai", 2.0), ("ai", -2.0)])
def test_invalid_rules_are_rejected(db_conn, topic, adjustment):
    with pytest.raises(ValueError):
        topics.set_rule(db_conn, topic, adjustment=adjustment)


# ── vocabulary ─────────────────────────────────────────────────────────────────

def test_vocabulary_returns_most_used_first(db_conn):
    """Feeding known slugs back into the prompt stops the model inventing a new
    synonym every run, which would leave the rules matching nothing."""
    fid = add_feed(db_conn)
    for i in range(3):
        add_article(db_conn, fid, seq=i, guid=f"a{i}", topics=["ai"])
    add_article(db_conn, fid, seq=9, guid="b", topics=["hardware"])
    vocab = topics.vocabulary(db_conn)
    assert vocab[0] == "ai" and "hardware" in vocab


def test_vocabulary_is_empty_on_a_fresh_install(db_conn):
    assert topics.vocabulary(db_conn) == []


def test_counts_joins_rules(db_conn):
    fid = add_feed(db_conn)
    add_article(db_conn, fid, topics=["ai"])
    topics.set_rule(db_conn, "ai", muted=True)
    db_conn.commit()
    row = topics.counts(db_conn)[0]
    assert row["topic"] == "ai" and row["n"] == 1 and row["muted"] is True


# ── scoring integration ────────────────────────────────────────────────────────

def _score(db, gen, **rule):
    from unittest.mock import patch
    from app.pipeline import score_new_articles
    if rule:
        topics.set_rule(db, **rule)
        db.commit()
    fid = add_feed(db)
    aid = add_article(db, fid, status="new", score=None)
    with patch("app.pipeline.ollama_client.generate", return_value=gen):
        score_new_articles(db, "profile")
    return db.execute(text(
        "SELECT score, status, topics, score_reason FROM articles WHERE id=:i"),
        {"i": aid}).mappings().first()


def test_scoring_stores_normalised_topics(db_conn):
    row = _score(db_conn, {"score": 0.8, "reason": "r", "topics": ["AI", "Formula 1"]})
    assert row["topics"] == ["ai", "formula-1"]


def test_scoring_without_topics_still_works(db_conn):
    """Older models, or a response missing the key, must not break scoring."""
    row = _score(db_conn, {"score": 0.8, "reason": "r"})
    assert row["topics"] is None and row["status"] == "scored"


def test_muted_topic_hides_the_article_at_scoring_time(db_conn):
    row = _score(db_conn, {"score": 0.95, "reason": "r", "topics": ["crypto"]},
                 topic="crypto", muted=True)
    assert row["status"] == "hidden"
    assert "Muted topic: crypto" in row["score_reason"]


def test_boost_lifts_an_article_over_the_threshold(db_conn):
    row = _score(db_conn, {"score": 0.30, "reason": "r", "topics": ["ai"]},
                 topic="ai", adjustment=0.2)
    assert row["score"] == pytest.approx(0.5)
    assert row["status"] == "scored"          # 0.30 alone would have been hidden


def test_prompt_carries_the_vocabulary():
    from app.prompts import scoring_prompt
    p = scoring_prompt("profile", "t", "s", vocabulary=["ai", "hardware"])
    assert "ai, hardware" in p
    assert "topics" in p


def test_prompt_without_vocabulary_says_so():
    from app.prompts import scoring_prompt
    assert "(none yet)" in scoring_prompt("p", "t", "s")


# ── routes ─────────────────────────────────────────────────────────────────────

def test_topic_panel_lists_topics(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), topics=["ai"])
        db.close()
    assert b"ai" in client.get("/settings/topics").data


@pytest.mark.parametrize("action,check", [
    ("mute", lambda r: r["muted"] is True),
    ("boost", lambda r: r["adjustment"] > 0),
    ("demote", lambda r: r["adjustment"] < 0),
])
def test_rule_actions(client, app, action, check):
    client.post("/settings/topics", data={"topic": "ai", "action": action})
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        assert check(topics.rules(db)["ai"])
        db.close()


def test_clear_removes_a_rule(client, app):
    client.post("/settings/topics", data={"topic": "ai", "action": "mute"})
    client.post("/settings/topics", data={"topic": "ai", "action": "clear"})
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        assert "ai" not in topics.rules(db)
        db.close()


def test_unknown_action_rejected(client):
    assert client.post("/settings/topics",
                       data={"topic": "ai", "action": "explode"}).status_code == 400


def test_blank_topic_reports_an_error(client):
    r = client.post("/settings/topics", data={"topic": "", "action": "mute"})
    assert b"Topic is required" in r.data


def test_articles_can_be_filtered_by_topic(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        add_article(db, fid, seq=1, guid="a", title="AI Story", topics=["ai"])
        add_article(db, fid, seq=2, guid="b", title="Bike Story", topics=["cycling"])
        db.close()
    data = client.get("/articles?topic=ai").data
    assert b"AI Story" in data and b"Bike Story" not in data


def test_topic_chips_render_on_cards(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), topics=["ai"])
        db.close()
    assert b"topic-chip" in client.get("/articles").data


def test_plain_users_cannot_change_rules(login_as):
    c, _ = login_as()
    assert c.post("/settings/topics", data={"topic": "ai", "action": "mute"}).status_code == 403


def test_invalid_stored_threshold_falls_back(db_conn):
    """A bad settings value must not stop scoring."""
    from unittest.mock import patch
    from app.db import set_setting
    from app.pipeline import score_new_articles, SCORE_THRESHOLD
    set_setting(db_conn, "score_threshold", "not-a-number")
    db_conn.commit()
    aid = add_article(db_conn, add_feed(db_conn), status="new", score=None)
    with patch("app.pipeline.ollama_client.generate",
               return_value={"score": 0.9, "reason": "r"}):
        score_new_articles(db_conn, "p")
    assert db_conn.execute(text("SELECT status FROM articles WHERE id=:i"),
                           {"i": aid}).scalar() == "scored"

"""Topic affinity: the reader's own votes as a scoring signal.

The measurement that motivated this, on the owner's 2,149 real votes, held out
5-fold: the model's relevance score separated likes from dislikes at AUC 0.524
-- a coin flip -- while their per-topic like-rates managed 0.756. Blending the
two scored 0.632, *worse* than affinity alone, which is why this replaces the
score rather than nudging it.
"""

import pytest
from sqlalchemy import text

from app import affinity
from tests.conftest import add_user


@pytest.fixture
def reader(db_conn):
    """A real user row: `votes.user_id` is a foreign key."""
    return add_user(db_conn, username="reader")


def _vote(db, user_id, value, topics, article_id=None):
    db.execute(text(
        "INSERT INTO votes (user_id, article_id, value, topics_snapshot) "
        "VALUES (:u, :a, :v, :t)"),
        {"u": user_id, "a": article_id, "v": value, "t": topics})


def _seed(db, user_id, likes=(), dislikes=()):
    """Enough volume to clear the evidence bar, plus the topics under test."""
    for i in range(20):
        _vote(db, user_id, 1, ["filler"])
        _vote(db, user_id, -1, ["filler"])
    for t in likes:
        _vote(db, user_id, 1, [t])
    for t in dislikes:
        _vote(db, user_id, -1, [t])
    db.commit()


def test_a_topic_the_reader_keeps_scores_above_one_they_reject(db_conn, reader):
    _seed(db_conn, reader, likes=["ai"] * 12, dislikes=["crime"] * 12)
    aff = affinity.topic_affinity(db_conn, reader)
    assert aff["ai"] > aff["crime"]
    assert aff["ai"] > 0.6 and aff["crime"] < 0.4


def test_a_topic_with_too_little_evidence_is_left_out(db_conn, reader):
    """Below the bar a topic is an anecdote. One vote must not move an article
    a long way -- least of all to a reader who can see that vote."""
    _seed(db_conn, reader, likes=["ai"] * 12, dislikes=["rare"])
    aff = affinity.topic_affinity(db_conn, reader)
    assert "ai" in aff
    assert "rare" not in aff


def test_smoothing_keeps_a_thin_topic_off_the_extremes(db_conn, reader):
    _seed(db_conn, reader, likes=["ai"] * 3)
    aff = affinity.topic_affinity(db_conn, reader)
    # Three likes and nothing else is not 100% affinity.
    assert 0.5 < aff["ai"] < 0.95


@pytest.mark.parametrize("likes,dislikes", [
    (2, 2),        # nowhere near enough votes
    (60, 2),       # plenty of votes, almost no dislikes
    (2, 60),       # and the mirror image
])
def test_affinity_stays_out_of_the_way_until_it_has_both_kinds(db_conn, reader, likes, dislikes):
    """Seen on a real database: 16 topic-carrying votes that were all likes
    gave every topic a smoothed rate of 1.0, so every article scored
    identically. That does not merely fail to help -- it destroys the ranking
    inside the kept set."""
    for _ in range(likes):
        _vote(db_conn, reader, 1, ["ai"])
    for _ in range(dislikes):
        _vote(db_conn, reader, -1, ["ai"])
    db_conn.commit()
    assert affinity.topic_affinity(db_conn, 1) == {}


def test_no_votes_at_all_is_not_an_error(db_conn):
    assert affinity.topic_affinity(db_conn, 1) == {}
    assert affinity.owner_id(db_conn) is None
    assert affinity.evidence_block(db_conn, 1) == ""


def test_the_owner_is_the_lowest_user_id(db_conn):
    first = add_user(db_conn, username="first")
    second = add_user(db_conn, username="second")
    _vote(db_conn, second, 1, ["ai"])
    _vote(db_conn, first, 1, ["ai"])
    db_conn.commit()
    assert affinity.owner_id(db_conn) == min(first, second)


# ── how it is applied ─────────────────────────────────────────────────────────

def test_the_readers_record_replaces_the_models_guess():
    score, note = affinity.adjust(0.05, ["ai"], {"ai": 0.9})
    assert score == 0.9, "not an average -- blending measured worse than either"
    assert "ai" in note


def test_the_model_stands_when_there_is_no_record():
    for topics, aff in ((["unseen"], {"ai": 0.9}), ([], {"ai": 0.9}), (["ai"], {})):
        score, note = affinity.adjust(0.42, topics, aff)
        assert score == 0.42
        assert note is None


def test_several_known_topics_average(db_conn):
    score, _ = affinity.adjust(0.0, ["ai", "crime"], {"ai": 1.0, "crime": 0.0})
    assert score == 0.5


def test_the_reason_says_it_came_from_the_readers_votes():
    _, note = affinity.adjust(0.1, ["ai"], {"ai": 0.9})
    # It appears beside the article, so it has to explain itself.
    assert note.startswith("Your votes on")


# ── the evidence block the prompts get ────────────────────────────────────────

def test_evidence_names_both_sides_with_counts(db_conn, reader):
    _seed(db_conn, reader, likes=["ai"] * 12, dislikes=["crime"] * 12)
    block = affinity.evidence_block(db_conn, reader)
    assert "Keeps:" in block and "ai" in block
    assert "Rejects:" in block and "crime" in block
    # Counts, not adjectives: the model wrote a profile claiming this reader
    # valued "crime and legal stories" when their like-rate on crime was 23%.
    assert "%" in block and "of" in block


def test_evidence_outranks_inference_in_so_many_words(db_conn, reader):
    _seed(db_conn, reader, likes=["ai"] * 12, dislikes=["crime"] * 12)
    assert "outrank" in affinity.evidence_block(db_conn, reader)


def test_a_topic_sitting_in_the_middle_produces_no_evidence_block(db_conn, reader):
    """Between 35% and 50% a topic says nothing useful either way, so there is
    nothing worth telling the model about it."""
    for _ in range(24):
        _vote(db_conn, reader, 1, ["borderline"])
    for _ in range(32):
        _vote(db_conn, reader, -1, ["borderline"])
    db_conn.commit()
    assert affinity.evidence_block(db_conn, reader) == ""


def test_scoring_writes_the_readers_record_into_the_reason(db_conn, reader):
    """End to end: the pipeline applies affinity and says so beside the article."""
    from unittest.mock import patch
    from tests.conftest import add_article, add_feed

    for _ in range(24):
        _vote(db_conn, reader, 1, ["formula-1"])
    for _ in range(24):
        _vote(db_conn, reader, -1, ["celebrity"])
    db_conn.commit()

    # status='new' and no score: that is what the scorer picks up.
    add_article(db_conn, add_feed(db_conn), seq=1, guid="aff",
                status="new", score=None)
    from app import pipeline
    reply = {"score": 0.05, "reason": "Routine race report.", "topics": ["formula-1"]}
    with patch("app.pipeline.ollama_client.generate", return_value=reply):
        assert pipeline.score_new_articles(db_conn, "profile") == 1

    row = db_conn.execute(text(
        "SELECT score, score_reason, status FROM articles")).mappings().first()
    # The model said 0.05; the reader has voted on formula-1 twenty-four times
    # and liked all of them. Their record wins.
    assert row["score"] > 0.5
    assert row["score_reason"].startswith("Your votes on formula-1")
    assert row["status"] == "scored", "no longer hidden"


# ── the second axis ───────────────────────────────────────────────────────────

def _vote_kind(db, user_id, value, kind, topics=None):
    db.execute(text(
        "INSERT INTO votes (user_id, value, topics_snapshot, kind_snapshot) "
        "VALUES (:u, :v, :t, :k)"),
        {"u": user_id, "v": value, "t": topics, "k": kind})


def test_a_kind_the_reader_rejects_scores_below_one_they_keep(db_conn, reader):
    for _ in range(20):
        _vote_kind(db_conn, reader, -1, "fixture")
        _vote_kind(db_conn, reader, 1, "transfer")
    db_conn.commit()
    ka = affinity.kind_affinity(db_conn, reader)
    assert ka["fixture"] < 0.3 < ka["transfer"]


def test_the_kind_pulls_down_a_subject_the_reader_otherwise_likes(db_conn):
    """The case this axis was built for. `boca-juniors` sits at 48% -- noise --
    because it holds both fixture listings and transfer news."""
    topic = {"boca-juniors": 0.48}
    fixture, _ = affinity.adjust(0.9, ["boca-juniors"], topic, "fixture", {"fixture": 0.12})
    transfer, _ = affinity.adjust(0.9, ["boca-juniors"], topic, "transfer", {"transfer": 0.71})
    assert fixture < 0.35 < transfer, "same subject, opposite outcome"


def test_the_kind_alone_is_enough_when_the_subject_is_unknown(db_conn):
    score, note = affinity.adjust(0.8, ["never-seen"], {}, "fixture", {"fixture": 0.12})
    assert score == 0.12
    assert "fixture articles" in note


def test_the_reason_names_both_axes(db_conn):
    _, note = affinity.adjust(0.5, ["boca-juniors"], {"boca-juniors": 0.5},
                              "fixture", {"fixture": 0.1})
    assert "boca-juniors" in note and "fixture" in note


def test_kind_affinity_needs_both_kinds_of_vote_too(db_conn, reader):
    for _ in range(60):
        _vote_kind(db_conn, reader, 1, "fixture")
    db_conn.commit()
    assert affinity.kind_affinity(db_conn, reader) == {}

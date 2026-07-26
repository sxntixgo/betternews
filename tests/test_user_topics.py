"""Per-user topic stances.

Scores are shared, so these cannot re-score anything — they shape one user's
list at read time. The tests that matter are the isolation ones: a stance must
never change what anyone else sees.
"""

import pytest
from sqlalchemy import text

from app import user_topics
from tests.conftest import add_article, add_feed, add_user


def _uid(db):
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db)
    db.commit()
    return uid


def _list(db, uid, **kw):
    from app.repo.articles import list_for_user
    return [r["title"] for r in list_for_user(db, uid, **kw)]


# ── setting stances ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stance", ["more", "hide"])
def test_a_stance_is_stored(db_conn, stance):
    uid = _uid(db_conn)
    user_topics.set_stance(db_conn, uid, "ai", stance)
    db_conn.commit()
    assert user_topics.stances(db_conn, uid) == {"ai": stance}


def test_a_stance_is_replaced_not_duplicated(db_conn):
    uid = _uid(db_conn)
    user_topics.set_stance(db_conn, uid, "ai", "more")
    user_topics.set_stance(db_conn, uid, "ai", "hide")
    db_conn.commit()
    assert user_topics.stances(db_conn, uid) == {"ai": "hide"}


def test_clearing_removes_the_stance(db_conn):
    uid = _uid(db_conn)
    user_topics.set_stance(db_conn, uid, "ai", "more")
    user_topics.set_stance(db_conn, uid, "ai", None)
    db_conn.commit()
    assert user_topics.stances(db_conn, uid) == {}


def test_topics_are_normalised_on_the_way_in(db_conn):
    """Otherwise a stance on "Futbol" never matches an article tagged
    "football"."""
    uid = _uid(db_conn)
    user_topics.set_stance(db_conn, uid, "Futbol", "more")
    db_conn.commit()
    assert "football" in user_topics.stances(db_conn, uid)


@pytest.mark.parametrize("topic,stance", [("", "more"), ("   ", "hide")])
def test_a_blank_topic_is_rejected(db_conn, topic, stance):
    with pytest.raises(ValueError):
        user_topics.set_stance(db_conn, _uid(db_conn), topic, stance)


def test_an_unknown_stance_is_rejected(db_conn):
    with pytest.raises(ValueError):
        user_topics.set_stance(db_conn, _uid(db_conn), "ai", "obliterate")


def test_reset_all_clears_everything(db_conn):
    uid = _uid(db_conn)
    user_topics.set_stance(db_conn, uid, "ai", "more")
    user_topics.set_stance(db_conn, uid, "sports", "hide")
    db_conn.commit()
    assert user_topics.clear_all(db_conn, uid) == 2
    db_conn.commit()
    assert user_topics.stances(db_conn, uid) == {}


# ── effect on the list ─────────────────────────────────────────────────────────

def test_hidden_topics_leave_the_list(db_conn):
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="a", title="Crypto Thing", topics=["crypto"])
    add_article(db_conn, fid, seq=2, guid="b", title="AI Thing", topics=["ai"])
    user_topics.set_stance(db_conn, uid, "crypto", "hide")
    db_conn.commit()
    titles = _list(db_conn, uid)
    assert "AI Thing" in titles and "Crypto Thing" not in titles


def test_untagged_articles_are_never_hidden(db_conn):
    """An overlap test against NULL would quietly swallow every untagged
    article."""
    uid = _uid(db_conn)
    add_article(db_conn, add_feed(db_conn), title="No Topics", topics=None)
    user_topics.set_stance(db_conn, uid, "crypto", "hide")
    db_conn.commit()
    assert "No Topics" in _list(db_conn, uid)


def test_a_boost_reorders_within_the_list(db_conn):
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="a", title="Higher Score",
                score=0.60, topics=["sports"])
    add_article(db_conn, fid, seq=2, guid="b", title="Boosted",
                score=0.50, topics=["ai"])
    assert _list(db_conn, uid, sort="score")[0] == "Higher Score"
    user_topics.set_stance(db_conn, uid, "ai", "more")
    db_conn.commit()
    assert _list(db_conn, uid, sort="score")[0] == "Boosted"


def test_a_boost_does_not_change_the_stored_score(db_conn):
    """Turning a stance off has to restore things exactly."""
    uid = _uid(db_conn)
    aid = add_article(db_conn, add_feed(db_conn), score=0.5, topics=["ai"])
    user_topics.set_stance(db_conn, uid, "ai", "more")
    db_conn.commit()
    _list(db_conn, uid, sort="score")
    assert db_conn.execute(text("SELECT score FROM articles WHERE id=:i"),
                           {"i": aid}).scalar() == pytest.approx(0.5)


def test_an_explicit_topic_filter_overrides_a_hide(db_conn):
    """Asking for a topic by name is a deliberate request."""
    uid = _uid(db_conn)
    add_article(db_conn, add_feed(db_conn), title="Crypto Thing", topics=["crypto"])
    user_topics.set_stance(db_conn, uid, "crypto", "hide")
    db_conn.commit()
    assert _list(db_conn, uid, topic="crypto") == ["Crypto Thing"]


def test_hidden_topics_leave_the_unread_count(db_conn):
    """A count that disagrees with the list is worse than no count."""
    from app.repo.articles import unread_count
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="a", topics=["crypto"])
    add_article(db_conn, fid, seq=2, guid="b", topics=["ai"])
    assert unread_count(db_conn, uid) == 2
    user_topics.set_stance(db_conn, uid, "crypto", "hide")
    db_conn.commit()
    assert unread_count(db_conn, uid) == 1


def test_the_digest_skips_hidden_topics(db_conn):
    from app import digest
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="a", title="Crypto", topics=["crypto"])
    add_article(db_conn, fid, seq=2, guid="b", title="AI", topics=["ai"])
    user_topics.set_stance(db_conn, uid, "crypto", "hide")
    db_conn.commit()
    assert [r["title"] for r in digest.unread_for(db_conn, uid)] == ["AI"]


# ── isolation ★ ────────────────────────────────────────────────────────────────

def test_one_users_stance_does_not_touch_another_list(db_conn):
    """The whole design constraint: scores are shared, stances are not."""
    a = _uid(db_conn)
    b = add_user(db_conn, username="second", role="user")
    add_article(db_conn, add_feed(db_conn), title="Crypto Thing", topics=["crypto"])
    user_topics.set_stance(db_conn, a, "crypto", "hide")
    db_conn.commit()
    assert _list(db_conn, a) == []
    assert _list(db_conn, b) == ["Crypto Thing"]


def test_boosts_are_per_user_too(db_conn):
    a = _uid(db_conn)
    b = add_user(db_conn, username="second", role="user")
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="x", title="High", score=0.6, topics=["sports"])
    add_article(db_conn, fid, seq=2, guid="y", title="Low", score=0.5, topics=["ai"])
    user_topics.set_stance(db_conn, a, "ai", "more")
    db_conn.commit()
    assert _list(db_conn, a, sort="score")[0] == "Low"
    assert _list(db_conn, b, sort="score")[0] == "High"


# ── the profile list ───────────────────────────────────────────────────────────

def test_profile_orders_by_the_users_own_engagement(db_conn):
    """A topic you have an opinion about beats whatever is merely numerous."""
    from app.repo.articles import record_vote
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    for i in range(5):
        add_article(db_conn, fid, seq=i, guid=f"c{i}", topics=["common"])
    voted = add_article(db_conn, fid, seq=9, guid="v", topics=["niche"])
    record_vote(db_conn, uid, voted, 1)
    db_conn.commit()
    assert user_topics.for_profile(db_conn, uid)[0]["topic"] == "niche"


def test_profile_reports_the_users_like_rate(db_conn):
    from app.repo.articles import record_vote
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    for i, v in enumerate((1, 1, -1)):
        record_vote(db_conn, uid, add_article(db_conn, fid, seq=i, guid=f"g{i}",
                                              topics=["ai"]), v)
    db_conn.commit()
    row = {r["topic"]: r for r in user_topics.for_profile(db_conn, uid)}["ai"]
    assert row["voted"] == 3 and row["like_rate"] == 67


def test_like_rate_is_none_without_votes(db_conn):
    uid = _uid(db_conn)
    add_article(db_conn, add_feed(db_conn), topics=["ai"])
    assert user_topics.for_profile(db_conn, uid)[0]["like_rate"] is None


def test_suggestions_come_from_the_users_own_voting(db_conn):
    from app.repo.articles import record_vote
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    for i in range(4):
        record_vote(db_conn, uid, add_article(db_conn, fid, seq=i, guid=f"l{i}",
                                              topics=["ai"]), 1)
    for i in range(4, 8):
        record_vote(db_conn, uid, add_article(db_conn, fid, seq=i, guid=f"d{i}",
                                              topics=["crypto"]), -1)
    db_conn.commit()
    hints = user_topics.suggestions(db_conn, uid)
    assert "ai" in hints["more"] and "crypto" in hints["hide"]


def test_suggestions_ignore_topics_already_set(db_conn):
    from app.repo.articles import record_vote
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    for i in range(4):
        record_vote(db_conn, uid, add_article(db_conn, fid, seq=i, guid=f"l{i}",
                                              topics=["ai"]), 1)
    user_topics.set_stance(db_conn, uid, "ai", "more")
    db_conn.commit()
    assert "ai" not in user_topics.suggestions(db_conn, uid)["more"]


def test_suggestions_need_enough_votes(db_conn):
    from app.repo.articles import record_vote
    uid = _uid(db_conn)
    record_vote(db_conn, uid, add_article(db_conn, add_feed(db_conn), topics=["ai"]), 1)
    db_conn.commit()
    assert user_topics.suggestions(db_conn, uid)["more"] == []


# ── routes ─────────────────────────────────────────────────────────────────────

def test_profile_page_shows_the_topic_section(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), topics=["ai"])
        db.close()
    assert b"Topics you care about" in client.get("/profile").data
    assert b"ai" in client.get("/profile/topics").data


@pytest.mark.parametrize("stance", ["more", "hide"])
def test_setting_a_stance_through_the_profile(client, app, stance):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), topics=["ai"])
        db.close()
    r = client.post("/profile/topics", data={"topic": "ai", "stance": stance})
    assert r.status_code == 200
    with app.app_context():
        db = get_db_direct()
        from app.repo.users import ensure_bootstrap_user
        assert user_topics.stances(db, ensure_bootstrap_user(db))["ai"] == stance
        db.close()


def test_clearing_through_the_profile(client, app):
    client.post("/profile/topics", data={"topic": "ai", "stance": "more"})
    client.post("/profile/topics", data={"topic": "ai", "stance": "clear"})
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        from app.repo.users import ensure_bootstrap_user
        assert user_topics.stances(db, ensure_bootstrap_user(db)) == {}
        db.close()


def test_reset_all_through_the_profile(client, app):
    client.post("/profile/topics", data={"topic": "ai", "stance": "more"})
    client.post("/profile/topics", data={"topic": "sports", "stance": "hide"})
    client.post("/profile/topics", data={"topic": "-", "stance": "reset-all"})
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        from app.repo.users import ensure_bootstrap_user
        assert user_topics.stances(db, ensure_bootstrap_user(db)) == {}
        db.close()


def test_a_bad_stance_reports_an_error(client):
    r = client.post("/profile/topics", data={"topic": "ai", "stance": "explode"})
    assert b"Stance must be one of" in r.data


def test_changing_a_stance_invalidates_the_digest(client, app):
    """The digest covers unread articles, so hiding a topic changes it."""
    from app.db import get_db_direct
    from unittest.mock import patch
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        for i in range(3):
            add_article(db, fid, seq=i, guid=f"g{i}", topics=["ai"])
        db.close()
    with patch("app.ollama_client.generate", return_value="brief"):
        client.get("/digest")
    client.post("/profile/topics", data={"topic": "sports", "stance": "hide"})
    with app.app_context():
        db = get_db_direct()
        assert db.execute(text("SELECT COUNT(*) FROM digests")).scalar() == 0
        db.close()


def test_plain_users_manage_their_own_topics(login_as):
    """This is a personal setting, not an admin one."""
    c, _ = login_as()
    assert c.get("/profile/topics").status_code == 200
    assert c.post("/profile/topics",
                  data={"topic": "ai", "stance": "more"}).status_code == 200


def test_topic_preferences_require_a_session(anon_client):
    assert anon_client.get("/profile/topics").status_code == 302

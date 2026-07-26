"""Cross-feed duplicate clustering. No LLM — canonical URLs and title overlap."""

import pytest
from sqlalchemy import text

from app import dedupe
from tests.conftest import add_article, add_feed


# ── canonical URLs ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("https://x.com/story", "https://www.x.com/story"),
    ("https://x.com/story", "http://x.com/story"),
    ("https://x.com/story", "https://x.com/story/"),
    ("https://x.com/story", "https://x.com/story?utm_source=twitter&utm_medium=social"),
    ("https://x.com/story", "https://x.com/story?fbclid=abc123"),
    ("https://x.com/story", "https://X.COM/story"),
])
def test_tracking_noise_collapses(a, b):
    assert dedupe.canonical_url(a) == dedupe.canonical_url(b)


@pytest.mark.parametrize("a,b", [
    ("https://x.com/one", "https://x.com/two"),
    ("https://x.com/s?id=1", "https://x.com/s?id=2"),
    ("https://a.com/s", "https://b.com/s"),
])
def test_genuinely_different_urls_stay_apart(a, b):
    assert dedupe.canonical_url(a) != dedupe.canonical_url(b)


def test_meaningful_query_params_are_kept():
    assert "id=42" in dedupe.canonical_url("https://x.com/s?id=42&utm_source=t")


@pytest.mark.parametrize("bad", ["", None])
def test_canonical_url_handles_empty(bad):
    assert dedupe.canonical_url(bad) == ""


# ── title similarity ───────────────────────────────────────────────────────────

def test_same_story_different_outlets_matches():
    a = "Apple announces new M5 chip for MacBook Pro"
    b = "Apple unveils the new M5 chip in MacBook Pro"
    assert dedupe.similarity(a, b) >= dedupe.SIMILARITY_THRESHOLD


def test_word_order_does_not_matter():
    assert dedupe.title_key("Apple announces M5 chip today") == \
           dedupe.title_key("today chip M5 announces Apple")


def test_unrelated_headlines_do_not_match():
    a = "Apple announces new M5 chip for MacBook Pro"
    b = "Council approves the annual transport budget"
    assert dedupe.similarity(a, b) < dedupe.SIMILARITY_THRESHOLD


def test_short_headlines_never_cluster():
    """Too little signal — a false cluster hides a real story."""
    assert dedupe.similarity("Apple M5", "Apple M4") == 0.0


def test_stopwords_are_ignored():
    assert dedupe.title_tokens("the quick brown fox and a dog") == \
           frozenset({"quick", "brown", "fox", "dog"})


# ── clustering ─────────────────────────────────────────────────────────────────

def test_same_url_joins_the_same_cluster(db_conn):
    fid = add_feed(db_conn)
    k = dedupe.cluster_for(db_conn, "https://x.com/s", "A story about things")
    add_article(db_conn, fid, url="https://x.com/s", cluster_id=k)
    again = dedupe.cluster_for(db_conn, "https://www.x.com/s?utm_source=t",
                               "Totally different words here")
    assert again == k


def test_similar_titles_join_the_same_cluster(db_conn):
    fid = add_feed(db_conn)
    k = dedupe.cluster_for(db_conn, "https://a.com/s",
                           "Apple announces new M5 chip for MacBook Pro")
    add_article(db_conn, fid, url="https://a.com/s", cluster_id=k,
                title="Apple announces new M5 chip for MacBook Pro")
    other = dedupe.cluster_for(db_conn, "https://b.com/s",
                               "Apple unveils the new M5 chip in MacBook Pro")
    assert other == k


def test_unrelated_articles_get_their_own_cluster(db_conn):
    fid = add_feed(db_conn)
    k = dedupe.cluster_for(db_conn, "https://a.com/s", "Apple announces M5 chip today")
    add_article(db_conn, fid, url="https://a.com/s", cluster_id=k,
                title="Apple announces M5 chip today")
    other = dedupe.cluster_for(db_conn, "https://b.com/s",
                               "Council approves annual transport budget")
    assert other != k


def test_old_articles_are_outside_the_window(db_conn):
    """The same headline six months later is a different story."""
    fid = add_feed(db_conn)
    k = dedupe.cluster_for(db_conn, "https://a.com/s", "Apple announces M5 chip today")
    aid = add_article(db_conn, fid, url="https://a.com/s", cluster_id=k,
                      title="Apple announces M5 chip today")
    db_conn.execute(text(
        "UPDATE articles SET created_at = now() - interval '200 days' WHERE id=:i"),
        {"i": aid})
    db_conn.commit()
    assert dedupe.cluster_for(db_conn, "https://b.com/s",
                              "Apple announces M5 chip today") != k


# ── list collapsing ────────────────────────────────────────────────────────────

def test_duplicates_collapse_to_the_best_scoring_member(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        add_article(db, fid, seq=1, guid="a", title="Verge take", score=0.6,
                    cluster_id="c1")
        add_article(db, fid, seq=2, guid="b", title="Ars take", score=0.9,
                    cluster_id="c1")
        db.close()
    data = client.get("/articles?sort=score").data
    assert b"Ars take" in data           # higher score represents the cluster
    assert b"Verge take" not in data
    assert b"other feed" in data         # but the duplicate is acknowledged


def test_unclustered_articles_are_untouched(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        add_article(db, fid, seq=1, guid="a", title="One")
        add_article(db, fid, seq=2, guid="b", title="Two")
        db.close()
    data = client.get("/articles").data
    assert b"One" in data and b"Two" in data


def test_malformed_url_degrades_instead_of_raising():
    """A feed can emit anything; ingest must not die on it."""
    assert dedupe.canonical_url("http://[bad-ipv6") == "http://[bad-ipv6"


def test_nonstandard_port_is_significant():
    assert dedupe.canonical_url("https://x.com:8443/s") != dedupe.canonical_url("https://x.com/s")
    assert dedupe.canonical_url("https://x.com:443/s") == dedupe.canonical_url("https://x.com/s")


def test_collapsing_stops_at_the_page_limit(client, app):
    """Over-fetching must not spill past the requested page size."""
    from app.db import get_db_direct
    from app.repo.articles import list_for_user
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        uid = ensure_bootstrap_user(db)
        fid = add_feed(db)
        for i in range(8):
            add_article(db, fid, seq=i, guid=f"g{i}", cluster_id=f"c{i}")
        db.commit()
        rows = list_for_user(db, uid, limit=3)
        db.close()
    assert len(rows) == 3

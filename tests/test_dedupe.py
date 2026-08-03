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


# ── paging past collapsed duplicates ──────────────────────────────────────────

def test_paging_is_exact_now_that_collapsing_happens_in_sql(db_conn):
    """LIMIT/OFFSET applies to collapsed rows, so the offset counts articles
    the reader sees. No over-fetch, no correction, no overlap."""
    from app.repo.articles import list_for_user
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db_conn)
    fid = add_feed(db_conn)
    for i in range(12):
        for copy in range(2):
            add_article(db_conn, fid, seq=i * 2 + copy, guid=f"g{i}-{copy}",
                        title=f"Story {i}", cluster_id=f"c{i}")
    db_conn.commit()

    page = list_for_user(db_conn, uid, limit=4)
    assert len(page) == 4
    assert page.next_offset == 4, "the offset counts articles, not source rows"

    second = list_for_user(db_conn, uid, limit=4, offset=page.next_offset)
    assert not ({r["title"] for r in page} & {r["title"] for r in second})


def test_the_last_page_reports_no_next_offset(db_conn):
    from app.repo.articles import list_for_user
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db_conn)
    fid = add_feed(db_conn)
    for i in range(3):
        add_article(db_conn, fid, seq=i, guid=f"g{i}")
    db_conn.commit()
    page = list_for_user(db_conn, uid, limit=10)
    assert len(page) == 3
    assert page.next_offset is None


def test_a_cluster_straddling_the_page_boundary_is_not_repeated(db_conn):
    """Was a strict xfail: collapsing in Python over an offset window meant page
    two started with an empty seen-map and re-emitted a cluster page one had
    already shown. Collapsing in SQL removes the whole class."""
    from app.repo.articles import list_for_user
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db_conn)
    fid = add_feed(db_conn)
    for i in range(12):
        for copy in range(2):
            add_article(db_conn, fid, seq=i * 2 + copy, guid=f"s{i}-{copy}",
                        title=f"Story {i}", cluster_id=f"k{i}")
    db_conn.commit()

    page = list_for_user(db_conn, uid, limit=4)
    second = list_for_user(db_conn, uid, limit=4, offset=page.next_offset)
    assert not ({r["title"] for r in page} & {r["title"] for r in second})


# ── collapsing in SQL: the ways it can go wrong ───────────────────────────────

def test_unclustered_articles_are_not_collapsed_into_one(db_conn):
    """The loudest failure mode. DISTINCT ON over a NULL cluster_id groups every
    un-clustered article together, and the list drops to a single row."""
    from app.repo.articles import list_for_user
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db_conn)
    fid = add_feed(db_conn)
    for i in range(8):
        add_article(db_conn, fid, seq=i, guid=f"n{i}", title=f"Alone {i}",
                    cluster_id=None)
    db_conn.commit()
    page = list_for_user(db_conn, uid, limit=50)
    assert len(page) == 8, "each un-clustered article is a cluster of one"
    assert all(r["duplicate_count"] == 0 for r in page)


def test_a_mix_of_clustered_and_unclustered(db_conn):
    from app.repo.articles import list_for_user
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db_conn)
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="c1", title="Carried", cluster_id="k")
    add_article(db_conn, fid, seq=2, guid="c2", title="Carried", cluster_id="k")
    add_article(db_conn, fid, seq=3, guid="c3", title="Carried", cluster_id="k")
    add_article(db_conn, fid, seq=4, guid="s1", title="Solo", cluster_id=None)
    db_conn.commit()
    page = list_for_user(db_conn, uid, limit=50)
    by_title = {r["title"]: r for r in page}
    assert set(by_title) == {"Carried", "Solo"}
    assert by_title["Carried"]["duplicate_count"] == 2, "two other copies"
    assert by_title["Solo"]["duplicate_count"] == 0


def test_paging_the_whole_list_yields_every_article_once(db_conn):
    """200 articles, pages of 10, some clustered: 200 distinct ids, no repeats."""
    from app.repo.articles import list_for_user
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db_conn)
    fid = add_feed(db_conn)
    expected = 0
    seq = 0
    for i in range(200):
        # Every seventh article is carried by a second feed entry.
        cluster = f"k{i}" if i % 7 == 0 else None
        add_article(db_conn, fid, seq=seq, guid=f"p{seq}", title=f"Item {i}",
                    cluster_id=cluster)
        seq += 1
        expected += 1
        if cluster:
            add_article(db_conn, fid, seq=seq, guid=f"p{seq}", title=f"Item {i}",
                        cluster_id=cluster)
            seq += 1
    db_conn.commit()

    seen, offset = [], 0
    while True:
        page = list_for_user(db_conn, uid, limit=10, offset=offset)
        if not page:
            break
        seen.extend(r["id"] for r in page)
        if page.next_offset is None:
            break
        offset = page.next_offset

    assert len(seen) == len(set(seen)), "an article appeared on two pages"
    assert len(seen) == expected, f"expected {expected} distinct articles, got {len(seen)}"


def test_the_topic_boost_still_reorders_after_the_rewrite(db_conn):
    """effective_score carries the per-user boost, and the cluster winner is
    chosen with it -- a plain "highest stored score" would ignore the stance."""
    from app.repo.articles import list_for_user
    from app.repo.users import ensure_bootstrap_user
    from app.user_topics import set_stance
    uid = ensure_bootstrap_user(db_conn)
    fid = add_feed(db_conn)
    # BOOST is 0.15 -- deliberately enough to reorder within a page, not enough
    # to lift a poor article to the top. The fixture has to sit inside that.
    add_article(db_conn, fid, seq=1, guid="hi", title="Higher score",
                score=0.60, topics=["economy"])
    add_article(db_conn, fid, seq=2, guid="lo", title="Boosted", score=0.55,
                topics=["space"])
    db_conn.commit()

    plain = [r["title"] for r in list_for_user(db_conn, uid, sort="score")]
    assert plain[0] == "Higher score"

    set_stance(db_conn, uid, "space", "more")
    db_conn.commit()
    boosted = [r["title"] for r in list_for_user(db_conn, uid, sort="score")]
    assert boosted[0] == "Boosted", "the stance must still lift it"

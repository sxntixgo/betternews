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


# ── paging past collapsed duplicates ──────────────────────────────────────────

def test_the_next_page_starts_past_what_collapsing_consumed(db_conn):
    """Filling a page can take more source rows than it emits.

    Advancing the offset by the rows *returned* starts page 2 inside page 1 and
    the reader sees the same articles twice. The two counts are equal only when
    nothing collapsed, which is why this survived so long.
    """
    from app.repo.articles import list_for_user
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db_conn)
    fid = add_feed(db_conn)
    # Every article duplicated, so collapsing eats two source rows per output row.
    for i in range(12):
        for copy in range(2):
            add_article(db_conn, fid, seq=i * 2 + copy, guid=f"g{i}-{copy}",
                        title=f"Story {i}", cluster_id=f"c{i}")
    db_conn.commit()

    page = list_for_user(db_conn, uid, limit=4)
    assert len(page) == 4
    assert page.consumed > len(page), "collapsing must have eaten duplicates"
    assert page.next_offset == page.consumed, \
        f"offset must follow rows read, not rows shown ({len(page)})"

    # Page two no longer restarts inside page one, which is what the old
    # `offset + limit` did: it repeated most of the page.
    second = list_for_user(db_conn, uid, limit=4, offset=page.next_offset)
    overlap = {r["title"] for r in page} & {r["title"] for r in second}
    assert len(overlap) <= 1, f"page two largely repeated page one: {overlap}"


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


@pytest.mark.xfail(reason=(
    "Known limitation, not a regression. Collapsing happens in Python over an "
    "offset window, so a cluster whose copies straddle the page boundary is "
    "emitted again on the next page -- page two starts with an empty `seen` "
    "map and cannot know the cluster was already shown. Advancing by rows "
    "consumed (which this suite does cover) removes the wholesale repeat the "
    "old `offset + limit` caused, but not this. The real fix is to collapse in "
    "SQL -- DISTINCT ON (cluster_id) in a subquery, with the duplicate tally as "
    "a window function -- so LIMIT/OFFSET applies to already-collapsed rows."),
    strict=True)
def test_a_cluster_straddling_the_page_boundary_is_not_repeated(db_conn):
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

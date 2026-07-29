import io
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import pytest
from sqlalchemy import text


def _mark_read(db, article_id):
    from app.repo.articles import mark_read
    from app.repo.users import ensure_bootstrap_user
    mark_read(db, ensure_bootstrap_user(db), article_id)
    db.commit()


def _mark_saved(db, article_id):
    from app.repo.articles import toggle_saved
    from app.repo.users import ensure_bootstrap_user
    toggle_saved(db, ensure_bootstrap_user(db), article_id)
    db.commit()

from tests.conftest import add_article, add_feed


# ── Index + articles ───────────────────────────────────────────────────────────

def test_index_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Better News" in r.data


def test_settings_page_renders(client):
    r = client.get("/settings")
    assert r.status_code == 200
    assert b"Preference profile" in r.data
    assert b"Re-score hidden articles" in r.data
    # Manage-feeds widgets should NOT appear on the settings page anymore
    assert b"Add Feed" not in r.data
    assert b"Import OPML" not in r.data


def test_manage_feeds_page_renders(client):
    r = client.get("/manage-feeds")
    assert r.status_code == 200
    assert b"Add Feed" in r.data
    assert b"Import OPML" in r.data
    # Settings widgets should NOT appear here
    assert b"Preference Profile" not in r.data
    assert b"Ollama Models" not in r.data


def test_articles_empty(client):
    r = client.get("/articles")
    assert r.status_code == 200


def test_articles_shows_summarized(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, status="summarized", title="ShowMe")
        db.close()

    r = client.get("/articles")
    assert r.status_code == 200
    assert b"ShowMe" in r.data


def test_articles_shows_dismissed_greyed_out(client, app):
    """Dismissed is a state, not a deletion.

    Filtering them out made a dismissal indistinguishable from an article that
    never arrived — nothing to review and no way back. Retention is what
    removes an article, and never a starred one.
    """
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, status="dismissed", title="Dealt With")
        db.close()

    r = client.get("/articles")
    assert b"Dealt With" in r.data
    # The class the stylesheet greys out.
    assert b"article-row summarized dismissed" in r.data


def test_a_dismissed_article_is_not_unread(client, app):
    """Visible, but it must not keep inflating the badge."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, seq=1, guid="g-live", title="Live")
        add_article(db, feed_id, seq=2, guid="g-done", status="dismissed",
                    title="Done")
        db.close()
    assert client.get("/count").data.strip() == b"1"


def test_articles_sort_score(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, seq=1, guid="a", url="u1", title="LowScore", score=0.1)
        add_article(db, feed_id, seq=2, guid="b", url="u2", title="HiScore", score=0.99)
        db.close()
    r = client.get("/articles?sort=score")
    assert r.status_code == 200
    assert r.data.index(b"HiScore") < r.data.index(b"LowScore")


def test_articles_marks_read_class(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        article_id = add_article(db, feed_id, title="ReadOne")
        _mark_read(db, article_id)
        db.commit()
        db.close()
    r = client.get("/articles")
    assert b"read" in r.data
    assert b"ReadOne" in r.data


def test_articles_extracts_reading_time(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(
            db,
            feed_id,
            title="ReadingTimed",
            full_text="- 4 minutos de lectura\nsome content",
        )
        db.close()
    r = client.get("/articles")
    assert b"4" in r.data


# ── Vote ───────────────────────────────────────────────────────────────────────

def test_vote_like(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        article_id = add_article(db, feed_id)
        db.close()

    r = client.post(f"/vote/{article_id}/1")
    assert r.status_code == 200
    assert b"liked" in r.data

    with app.app_context():
        db = get_db_direct()
        row = db.execute(text(
            "SELECT opinion FROM user_article_state WHERE article_id=:p0"),
            {"p0": article_id}).mappings().first()
        assert row["opinion"] == "liked"
        vote = db.execute(text("SELECT value FROM votes WHERE article_id=:p0"), {"p0": article_id}).mappings().first()
        assert vote["value"] == 1
        db.close()


def test_vote_dislike(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        article_id = add_article(db, feed_id)
        db.close()

    r = client.post(f"/vote/{article_id}/-1")
    assert r.status_code == 200
    assert b"disliked" in r.data


def test_vote_invalid_value(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        article_id = add_article(db, feed_id)
        db.close()

    r = client.post(f"/vote/{article_id}/5")
    assert r.status_code == 400


def test_vote_non_numeric(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        article_id = add_article(db, feed_id)
        db.close()
    r = client.post(f"/vote/{article_id}/oops")
    assert r.status_code == 400


# ── Article content / read tracking ────────────────────────────────────────────

def test_article_content_marks_read(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        article_id = add_article(
            db, feed_id,
            full_text="Para leer.\nFirst paragraph here.\nSecond.",
        )
        db.close()
    r = client.get(f"/article/{article_id}/content")
    assert r.status_code == 200
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text("SELECT s.read_at FROM user_article_state s JOIN articles a ON a.id = s.article_id WHERE a.id=:p0"), {"p0": article_id}).mappings().first()
        assert row["read_at"] is not None
        db.close()


def test_article_content_404(client):
    r = client.get("/article/999999/content")
    assert r.status_code == 404


def test_article_content_uses_feed_content_fallback(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(
            db, feed_id,
            full_text=None,
            feed_content="Body from RSS feed_content tag.",
        )
        article_id = db.execute(text("SELECT id FROM articles")).mappings().first()["id"]
        db.close()
    r = client.get(f"/article/{article_id}/content")
    assert b"feed_content" in r.data


def test_count_endpoint(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, seq=1, guid="g1", status="summarized")
        add_article(db, feed_id, seq=2, guid="g2", status="liked")
        add_article(db, feed_id, seq=3, guid="g3", status="dismissed")
        db.close()
    r = client.get("/count")
    assert r.data == b"2"


# ── Feeds CRUD ─────────────────────────────────────────────────────────────────

def test_settings_page(client):
    r = client.get("/settings")
    assert r.status_code == 200


def test_feeds_list_empty(client):
    r = client.get("/feeds")
    assert r.status_code == 200
    assert b"No feeds" in r.data


def test_feeds_add(client, app):
    r = client.post("/feeds", data={"url": "https://hnrss.org/frontpage"})
    assert r.status_code == 200
    assert b"hnrss.org" in r.data


def test_feeds_add_empty_url(client):
    r = client.post("/feeds", data={"url": ""})
    assert r.status_code == 400


def test_feeds_add_duplicate(client):
    client.post("/feeds", data={"url": "https://example.com/rss"})
    r = client.post("/feeds", data={"url": "https://example.com/rss"})
    assert r.status_code == 409


def test_feeds_delete(client, app):
    client.post("/feeds", data={"url": "https://example.com/rss"})
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = db.execute(text("SELECT id FROM feeds")).mappings().first()["id"]
        db.close()
    r = client.delete(f"/feeds/{feed_id}")
    assert r.status_code == 200
    assert b"example.com" not in r.data


# ── OPML import / export ───────────────────────────────────────────────────────

def test_feeds_export_opml(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_feed(db, "https://example.com/rss")
        db.close()
    r = client.get("/feeds/opml")
    assert r.status_code == 200
    assert b"<opml" in r.data
    assert b"https://example.com/rss" in r.data
    assert "attachment" in r.headers["Content-Disposition"]


def test_feeds_import_opml_inserts_new(client, app):
    opml = b"""<?xml version="1.0"?>
    <opml version="2.0">
      <body>
        <outline type="rss" xmlUrl="https://a.example.com/rss"/>
        <outline type="rss" xmlUrl="https://b.example.com/atom"/>
      </body>
    </opml>"""
    data = {"file": (io.BytesIO(opml), "feeds.opml")}
    r = client.post("/feeds/opml", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    assert b"Imported 2" in r.data
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        urls = {row["url"] for row in db.execute(text("SELECT url FROM feeds")).mappings().all()}
        assert urls == {"https://a.example.com/rss", "https://b.example.com/atom"}
        db.close()


def test_feeds_import_opml_skips_duplicates(client, app):
    client.post("/feeds", data={"url": "https://dup.example.com/rss"})
    opml = b"""<?xml version="1.0"?>
    <opml><body>
      <outline xmlUrl="https://dup.example.com/rss"/>
      <outline xmlUrl="https://new.example.com/rss"/>
    </body></opml>"""
    r = client.post(
        "/feeds/opml",
        data={"file": (io.BytesIO(opml), "x.opml")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    assert b"Imported 1" in r.data


def test_feeds_import_opml_no_file(client):
    r = client.post("/feeds/opml", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_feeds_import_opml_invalid_xml(client):
    r = client.post(
        "/feeds/opml",
        data={"file": (io.BytesIO(b"not xml at all"), "f.opml")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400


def test_feeds_import_opml_empty(client):
    opml = b"<?xml version='1.0'?><opml><body></body></opml>"
    r = client.post(
        "/feeds/opml",
        data={"file": (io.BytesIO(opml), "f.opml")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400


# ── Status ─────────────────────────────────────────────────────────────────────

def test_status_html(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, status="summarized")
        db.close()
    r = client.get("/status")
    assert r.status_code == 200
    assert b"summarized" in r.data
    assert b"Articles by status" in r.data


def test_status_json(client, app):
    from app.db import get_db_direct, set_setting
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, status="summarized")
        set_setting(db, "last_pipeline_run_at", "2026-04-19T00:00:00Z")
        db.commit()
        db.close()
    r = client.get("/status", headers={"Accept": "application/json"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["feed_count"] == 1
    assert body["article_counts"]["summarized"] == 1
    assert body["last_pipeline_run_at"] == "2026-04-19T00:00:00Z"


# ── Models endpoint ────────────────────────────────────────────────────────────


def test_preferences_get_default(client):
    r = client.get("/preferences")
    assert r.status_code == 200
    assert b"Never updated" in r.data or b"profile" in r.data.lower()


def test_preferences_save(client, app):
    r = client.post("/preferences", data={"profile_text": "Loves Rust news."})
    assert r.status_code == 200
    assert b"Loves Rust news." in r.data
    assert b"Saved" in r.data
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text("SELECT profile_text FROM preferences WHERE id=1")).mappings().first()
        assert row["profile_text"] == "Loves Rust news."
        db.close()


@patch("threading.Thread")
def test_preferences_regenerate_spawns_thread(mock_thread, client):
    inst = mock_thread.return_value
    r = client.post("/preferences/regenerate")
    assert r.status_code == 200
    inst.start.assert_called_once()


# ── Manual poll ────────────────────────────────────────────────────────────────

@patch("threading.Thread")
def test_manual_poll_spawns_thread(mock_thread, client):
    inst = mock_thread.return_value
    r = client.post("/poll")
    assert r.status_code == 200
    inst.start.assert_called_once()


# ── Helpers ────────────────────────────────────────────────────────────────────

def test_extract_reading_time_english():
    from app.presenters import extract_reading_time
    assert extract_reading_time("This article is 7 min read.") == "7"


def test_extract_reading_time_spanish():
    from app.presenters import extract_reading_time
    assert extract_reading_time("- 4 minutos de lectura") == "4"


def test_extract_reading_time_none():
    from app.presenters import extract_reading_time
    assert extract_reading_time("no reading time here") is None


def test_clean_content_strips_reading_time():
    from app.presenters import clean_content
    text = (
        "Real first paragraph " * 20 + "\n"
        "- 4 minutos de lectura\n"
        "Otras noticias\n"
    )
    out = clean_content(text, title="Real first paragraph")
    assert "lectura" not in out.lower()
    # Junk is no longer deleted here — content_filter classifies it instead, so
    # the reader can fold it recoverably rather than truncating the body.
    assert "Otras noticias" in out


def test_clean_content_skips_duplicate_title_line():
    from app.presenters import clean_content
    out = clean_content("Some Title\nFirst paragraph.", title="Some Title")
    assert out.startswith("First paragraph")


def test_clean_content_skips_duplicate_description_line():
    from app.presenters import clean_content
    desc = "This is the description that leads the article and should not repeat."
    out = clean_content(desc + "\nReal body line.", description=desc)
    assert out.startswith("Real body line")


def test_clean_content_keeps_pagination_for_the_filter_to_classify():
    from app.presenters import clean_content
    body = ("Real first paragraph " * 30).strip() + "\n- 1\nrelated thing"
    out = clean_content(body)
    assert "- 1" in out
    assert "related thing" in out


def test_to_blocks_groups_consecutive_dash_bullets():
    from app.presenters import to_blocks
    text = "Intro paragraph.\n- first\n- second\n- third\nClosing line."
    blocks = to_blocks(text)
    assert blocks[0] == {"type": "p", "text": "Intro paragraph."}
    assert blocks[1] == {"type": "ul", "items": ["first", "second", "third"]}
    assert blocks[2] == {"type": "p", "text": "Closing line."}


def test_to_blocks_supports_star_and_unicode_bullets():
    from app.presenters import to_blocks
    blocks = to_blocks("* alpha\n• beta\n– gamma\nplain")
    assert blocks[0]["type"] == "ul"
    assert blocks[0]["items"] == ["alpha", "beta", "gamma"]
    assert blocks[1] == {"type": "p", "text": "plain"}


def test_to_blocks_separate_bullet_groups():
    from app.presenters import to_blocks
    blocks = to_blocks("- a\n- b\nbreak\n- c")
    assert [b["type"] for b in blocks] == ["ul", "p", "ul"]
    assert blocks[0]["items"] == ["a", "b"]
    assert blocks[2]["items"] == ["c"]


def test_to_blocks_ignores_empty_input():
    from app.presenters import to_blocks
    assert to_blocks("") == []


def test_to_blocks_emits_twitter_embed_when_enabled():
    from app.presenters import to_blocks
    text = "Setup line.\nhttps://twitter.com/jack/status/20\nFollow-up."
    blocks = to_blocks(text, embeds_enabled=True)
    assert blocks[1] == {
        "type": "embed",
        "platform": "twitter",
        "url": "https://twitter.com/jack/status/20",
    }


def test_to_blocks_recognises_x_com_and_instagram():
    from app.presenters import to_blocks
    text = (
        "https://x.com/elon/status/1234567890\n"
        "https://www.instagram.com/p/AbCdEf-12_/\n"
        "https://www.instagram.com/reel/XyZ123/"
    )
    blocks = to_blocks(text, embeds_enabled=True)
    assert [b["platform"] for b in blocks] == ["twitter", "instagram", "instagram"]
    assert all(b["type"] == "embed" for b in blocks)


def test_to_blocks_embed_disabled_keeps_url_as_paragraph():
    from app.presenters import to_blocks
    url = "https://twitter.com/jack/status/20"
    blocks = to_blocks(url)
    assert blocks == [{"type": "p", "text": url}]


def test_to_blocks_inline_url_is_not_an_embed():
    from app.presenters import to_blocks
    text = "Check https://twitter.com/jack/status/20 — interesting."
    blocks = to_blocks(text, embeds_enabled=True)
    assert blocks[0]["type"] == "p"
    assert "twitter.com" in blocks[0]["text"]


def test_to_blocks_embed_breaks_running_bullet_list():
    from app.presenters import to_blocks
    text = "- one\n- two\nhttps://twitter.com/u/status/9\n- three"
    blocks = to_blocks(text, embeds_enabled=True)
    assert [b["type"] for b in blocks] == ["ul", "embed", "ul"]
    assert blocks[0]["items"] == ["one", "two"]
    assert blocks[2]["items"] == ["three"]


def test_article_content_renders_twitter_embed_when_enabled(client, app):
    from app.db import get_db_direct, set_setting
    body = "Lead.\nhttps://twitter.com/jack/status/20\nTrailing."
    with app.app_context():
        db = get_db_direct()
        set_setting(db, "embeds_enabled", "1")
        feed_id = add_feed(db)
        add_article(db, feed_id, full_text=body)
        article_id = db.execute(text("SELECT id FROM articles")).mappings().first()["id"]
        db.commit()
        db.close()
    r = client.get(f"/article/{article_id}/content")
    html = r.data.decode()
    assert 'class="twitter-tweet"' in html
    assert 'data-embed-platform="twitter"' in html
    assert "https://twitter.com/jack/status/20" in html


def test_article_content_skips_embed_when_setting_off(client, app):
    from app.db import get_db_direct
    body = "Lead.\nhttps://twitter.com/jack/status/20\nTrailing."
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, full_text=body)
        article_id = db.execute(text("SELECT id FROM articles")).mappings().first()["id"]
        db.close()
    r = client.get(f"/article/{article_id}/content")
    html = r.data.decode()
    assert "twitter-tweet" not in html
    assert "https://twitter.com/jack/status/20" in html


def test_refresh_button_uses_loading_spinner(client):
    """The Refresh button shows a spinner element (not a "Fetching…" sibling)."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.decode()
    assert 'id="poll-btn"' in body
    assert 'class="btn-loadable"' in body
    assert 'class="btn-spinner"' in body
    assert 'class="btn-label"' in body
    assert "Fetching" not in body
    assert 'id="poll-spinner"' not in body


def test_embeds_settings_form_renders(client):
    r = client.get("/settings/embeds")
    assert r.status_code == 200
    assert b"embeds_enabled" in r.data
    # Default is off — checkbox is not pre-checked.
    assert b"checked" not in r.data


def test_embeds_settings_post_toggles_setting(client, app):
    from app.db import get_db_direct, get_setting
    r = client.post("/settings/embeds", data={"embeds_enabled": "1"})
    assert r.status_code == 200
    assert b"checked" in r.data
    assert b"Saved." in r.data
    with app.app_context():
        db = get_db_direct()
        assert get_setting(db, "embeds_enabled") == "1"
        db.close()
    # Posting without the box turns it back off.
    r = client.post("/settings/embeds", data={})
    assert r.status_code == 200
    assert b"checked" not in r.data
    with app.app_context():
        db = get_db_direct()
        assert get_setting(db, "embeds_enabled") == ""
        db.close()


def test_article_content_renders_bulleted_list(client, app):
    from app.db import get_db_direct
    body = "Lead paragraph.\n- one\n- two\n- three\nAfter list."
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, full_text=body)
        article_id = db.execute(text("SELECT id FROM articles")).mappings().first()["id"]
        db.close()
    r = client.get(f"/article/{article_id}/content")
    body_html = r.data.decode()
    assert "<ul>" in body_html
    assert "<li>one</li>" in body_html
    assert "<li>two</li>" in body_html
    assert "<li>three</li>" in body_html
    # Bullet items should not also appear as paragraphs.
    assert "<p>- one</p>" not in body_html


def test_article_content_skips_description_when_full_text_repeats_it(client, app):
    from app.db import get_db_direct
    # _clean_content already strips a leading body line that duplicates the
    # description, so the rendered content shows desc + remaining body once.
    desc = "Short unique preamble."
    body = desc + " Extra words continuing the same line with fresh content."
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(
            db, feed_id,
            raw_snippet=desc,
            full_text=body,
        )
        article_id = db.execute(text("SELECT id FROM articles")).mappings().first()["id"]
        db.close()
    r = client.get(f"/article/{article_id}/content")
    assert r.data.count(b"Short unique preamble") == 1


def test_preferences_regenerate_thread_handles_exception(client, app, caplog):
    """Cover the except-branch in the inline _run() helper."""
    import logging
    caplog.set_level(logging.ERROR, logger="app.views.settings")
    with patch("app.pipeline.regenerate_preferences", side_effect=RuntimeError("boom")):
        # Force the spawned thread to run inline so the except path is exercised.
        with patch("threading.Thread") as mock_thread:
            def fake_thread(target, daemon=False):
                t = MagicMock()
                t.start = lambda: target()
                return t
            mock_thread.side_effect = fake_thread
            r = client.post("/preferences/regenerate")
            assert r.status_code == 200
    assert "Manual preference regeneration failed" in caplog.text


def test_manual_poll_thread_handles_exception(client, app, caplog):
    import logging
    caplog.set_level(logging.ERROR, logger="app.views.ops")
    with patch("app.feeds.poll_all_feeds", side_effect=RuntimeError("netdown")):
        with patch("threading.Thread") as mock_thread:
            def fake_thread(target, daemon=False):
                t = MagicMock()
                t.start = lambda: target()
                return t
            mock_thread.side_effect = fake_thread
            r = client.post("/poll")
            assert r.status_code == 200
    assert "Manual poll failed" in caplog.text


def test_manual_poll_thread_runs_pipeline(client, app):
    """Cover the run_pipeline call inside the inline _run() helper."""
    with patch("app.feeds.poll_all_feeds") as mock_poll, \
         patch("app.pipeline.run_pipeline") as mock_pipeline, \
         patch("threading.Thread") as mock_thread:
        def fake_thread(target, daemon=False):
            t = MagicMock()
            t.start = lambda: target()
            return t
        mock_thread.side_effect = fake_thread
        r = client.post("/poll")
        assert r.status_code == 200
    mock_poll.assert_called_once()
    mock_pipeline.assert_called_once()


# ── Show-hidden filter + rescore-hidden ───────────────────────────────────────

def test_articles_pagination_emits_sentinel_when_full_page(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        for i in range(50):
            add_article(db, feed_id, seq=i, guid=f"g{i}")
        db.close()
    r = client.get("/articles")
    assert b"load-more" in r.data
    assert b"offset=50" in r.data


def test_articles_pagination_no_sentinel_on_partial_page(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        for i in range(10):
            add_article(db, feed_id, seq=i, guid=f"g{i}")
        db.close()
    r = client.get("/articles")
    assert b"load-more" not in r.data


def test_articles_pagination_offset(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        for i in range(60):
            add_article(db, feed_id, seq=i, guid=f"g{i}", title=f"Article{i}")
        db.close()
    r = client.get("/articles?offset=50")
    assert b"Article" in r.data
    # Only 10 left, no sentinel
    assert b"load-more" not in r.data


def test_articles_pagination_invalid_offset_falls_back_to_zero(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, title="OnFirstPage")
        db.close()
    r = client.get("/articles?offset=notanumber")
    assert b"OnFirstPage" in r.data


def test_articles_empty_page_2_does_not_show_empty_message(client, app):
    """A non-first page with no rows should render nothing, not the 'No articles' empty state."""
    r = client.get("/articles?offset=100")
    assert b"No articles yet" not in r.data


def test_articles_pagination_preserves_hidden_and_feed_filter(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        for i in range(50):
            add_article(db, feed_id, seq=i, guid=f"g{i}", status="hidden")
        db.close()
    r = client.get(f"/articles?hidden=1&feed={feed_id}")
    assert b"hidden=1" in r.data
    assert f"feed={feed_id}".encode() in r.data
    assert b"offset=50" in r.data


def test_articles_pagination_preserves_the_topic_filter(client, app):
    """Page 2 of a topic view must still be that topic, not everything."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        for i in range(50):
            add_article(db, feed_id, seq=i, guid=f"g{i}", status="summarized",
                        topics=["space-science"])
        db.close()
    r = client.get("/articles?topic=space-science")
    assert b"offset=50" in r.data
    assert b"topic=space-science" in r.data


def test_articles_pagination_escapes_a_topic_with_url_characters(client, app):
    from app.db import get_db_direct
    topic = "r&d science"
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        for i in range(50):
            add_article(db, feed_id, seq=i, guid=f"g{i}", status="summarized",
                        topics=[topic])
        db.close()
    r = client.get(f"/articles?topic={quote(topic)}")
    assert b"offset=50" in r.data
    # & would start a new query parameter and silently truncate the topic.
    assert b"topic=r%26d%20science" in r.data


def test_sidebar_feeds_lists_feeds_with_unread_counts(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        f1 = add_feed(db, url="https://a.example/rss", title="FeedA")
        f2 = add_feed(db, url="https://b.example/rss", title="FeedB")
        # FeedA: 2 unread summarized + 1 already-read summarized + 1 dismissed
        add_article(db, f1, seq=1, guid="a1", status="summarized")
        add_article(db, f1, seq=2, guid="a2", status="summarized")
        add_article(db, f1, seq=3, guid="a3", status="summarized",
                    read_at="2026-04-19T00:00:00Z")
        add_article(db, f1, seq=4, guid="a4", status="dismissed")
        # FeedB: nothing unread
        add_article(db, f2, seq=1, guid="b1", status="dismissed")
        db.close()
    r = client.get("/sidebar/feeds")
    assert r.status_code == 200
    assert b"FeedA" in r.data
    assert b"FeedB" in r.data
    # FeedA has 2 unread
    assert b">2<" in r.data
    # Total unread = 2
    assert b"All feeds" in r.data


def test_sidebar_feeds_no_unread_omits_badge(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db, title="Quiet")
        add_article(db, feed_id, status="dismissed")
        db.close()
    r = client.get("/sidebar/feeds")
    assert b"Quiet" in r.data
    assert b"sidebar-feed-count" not in r.data


def test_articles_feed_filter(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        f1 = add_feed(db, url="https://a.example/rss", title="FeedA")
        f2 = add_feed(db, url="https://b.example/rss", title="FeedB")
        add_article(db, f1, seq=1, guid="a1", title="ArticleFromA")
        add_article(db, f2, seq=2, guid="b1", title="ArticleFromB")
        db.close()
    r = client.get(f"/articles?feed={f1}")
    assert b"ArticleFromA" in r.data
    assert b"ArticleFromB" not in r.data


def test_articles_feed_filter_ignored_when_invalid(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, title="Visible")
        db.close()
    r = client.get("/articles?feed=notanumber")
    assert b"Visible" in r.data


def test_articles_hidden_filter_excludes_by_default(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, status="hidden", title="WasHidden")
        db.close()
    r = client.get("/articles")
    assert b"WasHidden" not in r.data


def test_articles_hidden_filter_shows_only_hidden(client, app):
    """?hidden=1 means ONLY hidden — not hidden-plus-normal-list."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, seq=1, guid="h", status="hidden", title="WasHidden")
        add_article(db, feed_id, seq=2, guid="s", status="summarized", title="Summarized")
        add_article(db, feed_id, seq=3, guid="l", status="liked", title="Liked")
        db.close()
    r = client.get("/articles?hidden=1")
    assert b"WasHidden" in r.data
    assert b"Summarized" not in r.data
    assert b"Liked" not in r.data


def test_rescore_hidden_requeues_and_runs_pipeline(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, seq=1, guid="h1", status="hidden", score=0.0)
        add_article(db, feed_id, seq=2, guid="h2", status="hidden", score=0.1)
        add_article(db, feed_id, seq=3, guid="ok", status="summarized", score=0.9)
        db.close()
    with patch("app.pipeline.run_pipeline") as mock_pipeline, \
         patch("threading.Thread") as mock_thread:
        def fake_thread(target, daemon=False):
            t = MagicMock()
            t.start = lambda: target()
            return t
        mock_thread.side_effect = fake_thread
        r = client.post("/rescore-hidden")
        assert r.status_code == 200
        assert b"requeued 2" in r.data
    mock_pipeline.assert_called_once()
    with app.app_context():
        db = get_db_direct()
        rows = {r["guid"]: r["status"] for r in db.execute(text("SELECT guid, status FROM articles")).mappings()}
        db.close()
    assert rows["h1"] == "new"
    assert rows["h2"] == "new"
    assert rows["ok"] == "summarized"


def test_dismiss_all_marks_summarized_liked_disliked(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, seq=1, guid="s", status="summarized")
        add_article(db, feed_id, seq=2, guid="l", status="liked")
        add_article(db, feed_id, seq=3, guid="d", status="disliked")
        add_article(db, feed_id, seq=4, guid="h", status="hidden", score=0.0)
        db.close()
    r = client.post("/dismiss-all")
    assert r.status_code == 200
    assert b"dismissed 3" in r.data
    with app.app_context():
        db = get_db_direct()
        rows = {r["guid"]: r["dismissed"] for r in db.execute(text(
            """SELECT a.guid, (s.dismissed_at IS NOT NULL) AS dismissed
               FROM articles a
               LEFT JOIN user_article_state s ON s.article_id = a.id"""
        )).mappings()}
        db.close()
    assert rows["s"] is True
    assert rows["l"] is True
    assert rows["d"] is True
    assert rows["h"] is False        # hidden articles are not in the list


def test_dismiss_all_respects_feed_filter(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        keep_feed = add_feed(db, url="https://keep.example/rss")
        drop_feed = add_feed(db, url="https://drop.example/rss")
        add_article(db, keep_feed, seq=1, guid="k", status="summarized")
        add_article(db, drop_feed, seq=2, guid="d", status="summarized")
        db.close()
    r = client.post(f"/dismiss-all?feed={drop_feed}")
    assert r.status_code == 200
    assert b"dismissed 1" in r.data
    with app.app_context():
        db = get_db_direct()
        rows = {r["guid"]: r["dismissed"] for r in db.execute(text(
            """SELECT a.guid, (s.dismissed_at IS NOT NULL) AS dismissed
               FROM articles a
               LEFT JOIN user_article_state s ON s.article_id = a.id"""
        )).mappings()}
        db.close()
    assert rows["k"] is False
    assert rows["d"] is True


def test_dismiss_all_ignores_non_numeric_feed_arg(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, status="summarized")
        db.close()
    r = client.post("/dismiss-all?feed=abc")
    assert r.status_code == 200
    assert b"dismissed 1" in r.data


def test_feed_pause_marks_paused(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        db.close()
    r = client.post(f"/feeds/{feed_id}/pause")
    assert r.status_code == 200
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text("SELECT paused FROM feeds WHERE id=:p0"), {"p0": feed_id}).mappings().first()
        db.close()
    assert row["paused"] == 1


def test_feed_resume_clears_paused_and_failures(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        db.execute(text("UPDATE feeds SET paused=true, consecutive_failures=7, last_error='boom' WHERE id=:p0"), {"p0": feed_id})
        db.commit()
        db.close()
    r = client.post(f"/feeds/{feed_id}/resume")
    assert r.status_code == 200
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text("SELECT paused, consecutive_failures, last_error FROM feeds WHERE id=:p0"), {"p0": feed_id}).mappings().first()
        db.close()
    assert row["paused"] == 0
    assert row["consecutive_failures"] == 0
    assert row["last_error"] is None


def test_feed_set_threshold_with_value(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        db.close()
    r = client.post(f"/feeds/{feed_id}/threshold", data={"score_threshold": "0.55"})
    assert r.status_code == 200
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text("SELECT score_threshold FROM feeds WHERE id=:p0"), {"p0": feed_id}).mappings().first()
        db.close()
    assert abs(row["score_threshold"] - 0.55) < 1e-6


def test_feed_set_threshold_clears_when_empty(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        db.execute(text("UPDATE feeds SET score_threshold=0.7 WHERE id=:p0"), {"p0": feed_id})
        db.commit()
        db.close()
    r = client.post(f"/feeds/{feed_id}/threshold", data={"score_threshold": ""})
    assert r.status_code == 200
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text("SELECT score_threshold FROM feeds WHERE id=:p0"), {"p0": feed_id}).mappings().first()
        db.close()
    assert row["score_threshold"] is None


def test_feed_set_threshold_invalid_returns_400(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        db.close()
    r = client.post(f"/feeds/{feed_id}/threshold", data={"score_threshold": "abc"})
    assert r.status_code == 400


def test_feed_set_threshold_out_of_range_returns_400(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        db.close()
    r = client.post(f"/feeds/{feed_id}/threshold", data={"score_threshold": "1.5"})
    assert r.status_code == 400


def test_article_save_toggles_on_and_off(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        article_id = add_article(db, feed_id, status="summarized")
        db.close()
    # First call → save
    r1 = client.post(f"/article/{article_id}/save")
    assert r1.status_code == 200
    assert b"saved" in r1.data  # the row class includes 'saved'
    # Second call → unsave
    r2 = client.post(f"/article/{article_id}/save")
    assert r2.status_code == 200
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text(
            "SELECT saved_at FROM user_article_state WHERE article_id=:p0"),
            {"p0": article_id}).mappings().first()
        db.close()
    assert row is None or row["saved_at"] is None


def test_article_save_404(client):
    r = client.post("/article/9999/save")
    assert r.status_code == 404


def test_articles_saved_filter_returns_only_saved(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        a_saved = add_article(db, feed_id, seq=1, guid="s", status="summarized", title="SavedOne")
        add_article(db, feed_id, seq=2, guid="u", status="summarized", title="UnsavedOne")
        _mark_saved(db, a_saved)
        db.commit()
        db.close()
    r = client.get("/articles?saved=1")
    assert b"SavedOne" in r.data
    assert b"UnsavedOne" not in r.data


def test_articles_saved_filter_pagination_qs(client, app):
    """Pagination sentinel preserves the saved=1 flag."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        for i in range(51):
            aid = add_article(
                db, feed_id, seq=i, guid=f"g{i}", status="summarized",
                title=f"S{i}",
            )
            _mark_saved(db, aid)
        db.commit()
        db.close()
    r = client.get("/articles?saved=1")
    assert b"saved=1" in r.data
    assert b"offset=50" in r.data


def test_search_empty_query_returns_no_articles(client):
    r = client.get("/search")
    assert r.status_code == 200
    # Empty result with empty list should not contain any article-row
    assert b"article-row" not in r.data


def test_search_returns_matching_articles(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, seq=1, guid="a", status="summarized",
                    title="Quantum computing breakthrough", summary="qubits coherent",
                    full_text="quantum quantum quantum")
        add_article(db, feed_id, seq=2, guid="b", status="summarized",
                    title="Cooking with cast iron", summary="seasoning a pan",
                    full_text="iron skillet care")
        db.close()
    r = client.get("/search?q=quantum")
    assert b"Quantum computing breakthrough" in r.data
    assert b"Cooking with cast iron" not in r.data


def test_search_handles_bad_query_gracefully(client, app):
    """websearch_to_tsquery tolerates junk that FTS5 MATCH would reject."""
    r = client.get('/search?q=")((&^%$')
    assert r.status_code == 200

def test_search_quotes_escape_double_quotes(client, app):
    """A user query with embedded quotes is safely doubled inside the FTS phrase."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        add_article(db, feed_id, status="summarized",
                    title='He said "hello"', summary="greet")
        db.close()
    r = client.get('/search?q=hello')
    assert b'hello' in r.data


def test_sidebar_feeds_includes_saved_count(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db, title="MyFeed")
        aid = add_article(db, feed_id, status="summarized")
        _mark_saved(db, aid)
        db.commit()
        db.close()
    r = client.get("/sidebar/feeds")
    assert b"Saved" in r.data
    # The saved badge for the group should reflect the count.
    assert b'data-mode="saved"' in r.data


def test_rescore_hidden_thread_handles_exception(client, app, caplog):
    import logging
    caplog.set_level(logging.ERROR, logger="app.views.ops")
    with patch("app.pipeline.run_pipeline", side_effect=RuntimeError("boom")):
        with patch("threading.Thread") as mock_thread:
            def fake_thread(target, daemon=False):
                t = MagicMock()
                t.start = lambda: target()
                return t
            mock_thread.side_effect = fake_thread
            r = client.post("/rescore-hidden")
            assert r.status_code == 200
    assert "Rescore failed" in caplog.text


# ── Tag system ─────────────────────────────────────────────────────────────────


def test_normalize_tags_lowercases_trims_dedupes_sorts():
    from app.views.feeds import _normalize_tags
    assert _normalize_tags("") == ""
    assert _normalize_tags(None) == ""
    assert _normalize_tags("Tech") == "tech"
    assert _normalize_tags("  tech , News  ") == "news,tech"
    assert _normalize_tags("tech,tech,news,Tech") == "news,tech"
    assert _normalize_tags(",,,") == ""


def test_split_tags_handles_empty_and_missing():
    from app.views.feeds import _split_tags
    assert _split_tags(None) == []
    assert _split_tags("") == []
    assert _split_tags("tech,news") == ["tech", "news"]


def test_feed_set_tags_stores_normalized_value(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        db.close()
    r = client.post(f"/feeds/{feed_id}/tags", data={"tags": " Tech, News, tech "})
    assert r.status_code == 200
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text("SELECT tags FROM feeds WHERE id=:p0"), {"p0": feed_id}).mappings().first()
        db.close()
    assert row["tags"] == "news,tech"


def test_feed_set_tags_empty_clears_to_null(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        db.execute(text("UPDATE feeds SET tags=:p0 WHERE id=:p1"), {"p0": "tech", "p1": feed_id})
        db.commit()
        db.close()
    r = client.post(f"/feeds/{feed_id}/tags", data={"tags": ""})
    assert r.status_code == 200
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text("SELECT tags FROM feeds WHERE id=:p0"), {"p0": feed_id}).mappings().first()
        db.close()
    assert row["tags"] is None


def test_sidebar_feeds_groups_by_tag(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        tech_id = add_feed(db, url="https://t.example.com/rss", title="TechFeed")
        news_id = add_feed(db, url="https://n.example.com/rss", title="NewsFeed")
        untagged_id = add_feed(db, url="https://u.example.com/rss", title="LonelyFeed")
        db.execute(text("UPDATE feeds SET tags='tech' WHERE id=:p0"), {"p0": tech_id})
        db.execute(text("UPDATE feeds SET tags='news' WHERE id=:p0"), {"p0": news_id})
        db.commit()
        db.close()
    r = client.get("/sidebar/feeds")
    body = r.data.decode()
    # Tag group headers (alphabetical: news, tech) render as uppercase label.
    assert 'data-group="tag-news"' in body
    assert 'data-group="tag-tech"' in body
    # Untagged feed sits in its own group.
    assert 'data-group="untagged"' in body
    assert "LonelyFeed" in body
    # Feeds appear inside their group's body.
    assert "TechFeed" in body and "NewsFeed" in body


def test_sidebar_feeds_with_no_tags_is_one_group(client, app):
    """"All feeds" and a "Feeds" group below it were the same list under two
    headings. Untagged feeds nest under "All feeds" instead."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_feed(db, title="OnlyFeed")
        db.close()
    body = client.get("/sidebar/feeds").data.decode()
    assert "All feeds" in body
    assert "OnlyFeed" in body
    # Neither of the second headings survives.
    assert 'data-group="untagged"' not in body
    assert "Feeds</span>" not in body
    assert "Untagged" not in body
    # The feed sits inside the All-feeds group, not in one of its own.
    all_group = body.split('data-group="all"')[1].split('data-group=')[0]
    assert "OnlyFeed" in all_group


def test_sidebar_keeps_untagged_separate_once_tags_exist(client, app):
    """With tags doing the organising, leftovers are a real category again."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        tagged = add_feed(db, url="https://a.example/r", title="Tagged")
        add_feed(db, url="https://b.example/r", title="Loose")
        db.execute(text("UPDATE feeds SET tags = ARRAY['sports'] WHERE id = :i"),
                   {"i": tagged})
        db.commit()
        db.close()
    body = client.get("/sidebar/feeds").data.decode()
    assert 'data-group="untagged"' in body
    assert "Untagged" in body
    assert "sports" in body


def test_sidebar_feeds_feed_in_multiple_tags(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db, title="Multi")
        db.execute(text("UPDATE feeds SET tags='news,tech' WHERE id=:p0"), {"p0": fid})
        db.commit()
        db.close()
    r = client.get("/sidebar/feeds")
    body = r.data.decode()
    # The feed appears under BOTH tag groups.
    assert body.count("Multi") >= 2


# ── Single-article dismiss (swipe-left) ────────────────────────────────────────


def test_article_dismiss_marks_dismissed(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        aid = add_article(db, feed_id, status="summarized")
        db.close()
    r = client.post(f"/article/{aid}/dismiss")
    assert r.status_code == 200
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text(
            "SELECT dismissed_at FROM user_article_state WHERE article_id=:p0"),
            {"p0": aid}).mappings().first()
        db.close()
    assert row is not None and row["dismissed_at"] is not None


def test_article_dismiss_unknown_returns_404(client):
    r = client.post("/article/999999/dismiss")
    assert r.status_code == 404


# ── Favicon badge ──────────────────────────────────────────────────────────────


def test_favicon_link_present_on_index(client):
    r = client.get("/")
    assert b'id="favicon"' in r.data
    # SVG fallback URL is data: URI so the tab has a glyph before JS runs.
    assert b"data:image/svg+xml" in r.data


def test_favicon_link_present_on_settings(client):
    r = client.get("/settings")
    assert b'id="favicon"' in r.data


# ── Ollama connection settings ─────────────────────────────────────────────────

def _set_ollama(app, host, port):
    from app.db import get_db_direct, set_setting
    with app.app_context():
        db = get_db_direct()
        set_setting(db, "ollama_host", host)
        set_setting(db, "ollama_port", port)
        db.commit()
        db.close()


def test_ollama_form_shows_env_default_when_unset(client):
    r = client.get("/settings/ollama")
    assert r.status_code == 200
    assert b"OLLAMA_HOST" in r.data


def test_ollama_save_persists_and_reports(client, app):
    r = client.post("/settings/ollama",
                    data={"ollama_host": "10.0.10.207", "ollama_port": "11434"})
    assert r.status_code == 200
    assert b"Saved" in r.data
    from app.db import get_db_direct, get_setting
    with app.app_context():
        db = get_db_direct()
        assert get_setting(db, "ollama_host") == "10.0.10.207"
        assert get_setting(db, "ollama_port") == "11434"
        db.close()


def test_ollama_save_rejects_bad_port(client, app):
    r = client.post("/settings/ollama",
                    data={"ollama_host": "10.0.10.207", "ollama_port": "70000"})
    assert r.status_code == 200
    assert b"between 1 and 65535" in r.data
    from app.db import get_db_direct, get_setting
    with app.app_context():
        db = get_db_direct()
        assert get_setting(db, "ollama_host") == ""   # nothing persisted
        db.close()


def test_ollama_save_rejects_host_with_port(client):
    r = client.post("/settings/ollama",
                    data={"ollama_host": "10.0.10.207:11434", "ollama_port": "11434"})
    assert b"without a port" in r.data


def test_ollama_save_blank_reverts_to_env(client, app):
    _set_ollama(app, "10.0.10.207", "11434")
    r = client.post("/settings/ollama", data={"ollama_host": "", "ollama_port": ""})
    assert b"environment variable" in r.data
    from app.db import get_db_direct, get_setting
    with app.app_context():
        db = get_db_direct()
        assert get_setting(db, "ollama_host") == ""
        db.close()


@patch("app.views.settings.ollama_client.probe")
def test_ollama_test_uses_entered_values_without_saving(mock_probe, client, app):
    mock_probe.return_value = (True, "Connected to http://9.9.9.9:1234 — 1 model(s) installed.", ["a:1"])
    r = client.post("/settings/ollama/test",
                    data={"ollama_host": "9.9.9.9", "ollama_port": "1234"})
    assert r.status_code == 200
    assert b"1 model(s) installed" in r.data
    assert b"a:1" in r.data
    mock_probe.assert_called_once_with("http://9.9.9.9:1234")
    from app.db import get_db_direct, get_setting
    with app.app_context():
        db = get_db_direct()
        assert get_setting(db, "ollama_host") == ""   # probe must not persist
        db.close()


@patch("app.views.settings.ollama_client.probe")
def test_ollama_test_reports_failure(mock_probe, client):
    mock_probe.return_value = (False, "Connection refused — nothing listening on http://9.9.9.9:1234.", [])
    r = client.post("/settings/ollama/test",
                    data={"ollama_host": "9.9.9.9", "ollama_port": "1234"})
    assert b"Connection refused" in r.data
    assert b"ollama-result-bad" in r.data


def test_ollama_test_validates_before_probing(client):
    r = client.post("/settings/ollama/test",
                    data={"ollama_host": "bad host", "ollama_port": "1234"})
    assert b"not a valid hostname" in r.data


@patch("app.views.settings.ollama_client.probe")
def test_ollama_test_with_blank_fields_probes_env_default(mock_probe, client):
    mock_probe.return_value = (True, "ok", [])
    client.post("/settings/ollama/test", data={"ollama_host": "", "ollama_port": ""})
    from app import ollama_client as oc
    mock_probe.assert_called_once_with(oc.OLLAMA_BASE)



def _set_declickbait(app, on=True):
    from app.db import get_db_direct, set_setting
    with app.app_context():
        db = get_db_direct()
        set_setting(db, "declickbait_enabled", "1" if on else "")
        db.commit()
        db.close()


def _clickbait_article(app):
    from app.db import get_db_direct
    from tests.conftest import add_article, add_feed
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        aid = add_article(db, fid, title="You won't believe what happened")
        db.execute(text("UPDATE articles SET clean_title=:p0, title_was_clickbait=true WHERE id=:p1"), {"p0": "Council approves budget", "p1": aid})
        db.commit()
        db.close()
    return aid


def test_titles_setting_toggles(client, app):
    assert b"Rewrite clickbait headlines" in client.get("/settings/titles").data
    r = client.post("/settings/titles", data={"declickbait_enabled": "1"})
    assert b"Saved" in r.data
    from app.db import get_db_direct, get_setting
    with app.app_context():
        db = get_db_direct()
        assert get_setting(db, "declickbait_enabled") == "1"
        db.close()
    client.post("/settings/titles", data={})
    with app.app_context():
        db = get_db_direct()
        assert get_setting(db, "declickbait_enabled") == ""
        db.close()


def test_card_shows_rewrite_and_original_when_enabled(client, app):
    _clickbait_article(app)
    _set_declickbait(app, True)
    data = client.get("/articles").data
    assert b"Council approves budget" in data
    assert b"Originally:" in data
    assert b"You won&#39;t believe what happened" in data


def test_card_shows_original_only_when_disabled(client, app):
    _clickbait_article(app)
    _set_declickbait(app, False)
    data = client.get("/articles").data
    assert b"You won&#39;t believe what happened" in data
    assert b"Council approves budget" not in data
    assert b"Originally:" not in data


def test_card_unaffected_for_articles_without_rewrite(client, app):
    """Articles summarized before the feature existed must render unchanged."""
    from app.db import get_db_direct
    from tests.conftest import add_article, add_feed
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), title="Plain Headline")
        db.close()
    _set_declickbait(app, True)
    data = client.get("/articles").data
    assert b"Plain Headline" in data
    assert b"Originally:" not in data


def test_reader_modal_shows_rewrite_and_original(client, app):
    aid = _clickbait_article(app)
    _set_declickbait(app, True)
    data = client.get(f"/article/{aid}/content").data
    assert b"Council approves budget" in data
    assert b"Originally:" in data


def test_reader_modal_uses_original_when_disabled(client, app):
    aid = _clickbait_article(app)
    _set_declickbait(app, False)
    data = client.get(f"/article/{aid}/content").data
    assert b"You won&#39;t believe what happened" in data
    assert b"Originally:" not in data


def test_search_matches_original_title_while_showing_rewrite(client, app):
    """FTS indexes the stored title, so the published wording stays findable."""
    _clickbait_article(app)
    _set_declickbait(app, True)
    data = client.get("/search?q=believe").data
    assert b"Council approves budget" in data
    assert b"Originally:" in data


def test_vote_response_card_respects_setting(client, app):
    aid = _clickbait_article(app)
    _set_declickbait(app, True)
    data = client.post(f"/vote/{aid}/1").data
    assert b"Council approves budget" in data


# ── Content filter: reader rendering ───────────────────────────────────────────

def _set_filter(app, mode, llm=False):
    from app.db import get_db_direct, set_setting
    with app.app_context():
        db = get_db_direct()
        set_setting(db, "content_filter_mode", mode)
        set_setting(db, "content_filter_llm", "1" if llm else "")
        db.commit()
        db.close()


def _padded_article(app, body=None):
    from app.db import get_db_direct
    from tests.conftest import add_article, add_feed
    body = body or ("The council approved the budget on Tuesday.\n"
                    "The vote was seven to two.\n"
                    "Otras noticias\n"
                    "Some unrelated headline\n"
                    "Another unrelated headline")
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), full_text=body)
        db.commit()
        db.close()
    return aid


def test_filter_off_renders_everything_flat(client, app):
    aid = _padded_article(app)
    _set_filter(app, "off")
    data = client.get(f"/article/{aid}/content").get_data(as_text=True)
    assert "Otras noticias" in data
    assert "Some unrelated headline" in data
    assert "aside-block" not in data


def test_filter_remove_folds_padding_but_keeps_it(client, app):
    aid = _padded_article(app)
    _set_filter(app, "remove")
    data = client.get(f"/article/{aid}/content").get_data(as_text=True)
    assert "The council approved the budget" in data
    assert "aside-remove" in data
    assert "hidden — show" in data
    # Folded, never dropped — a misjudgement stays one click away.
    assert "Some unrelated headline" in data


def test_filter_highlight_labels_the_aside(client, app):
    aid = _padded_article(app)
    _set_filter(app, "highlight")
    data = client.get(f"/article/{aid}/content").get_data(as_text=True)
    assert "aside-highlight" in data
    assert "Related links" in data
    assert "Some unrelated headline" in data


def test_consecutive_asides_collapse_into_one_group(client, app):
    aid = _padded_article(app)
    _set_filter(app, "remove")
    data = client.get(f"/article/{aid}/content").get_data(as_text=True)
    assert data.count("<details") == 1
    assert "3 sections hidden" in data


def test_clean_article_has_no_aside_markup(client, app):
    aid = _padded_article(app, body="First paragraph.\nSecond paragraph.\nThird.")
    _set_filter(app, "remove")
    data = client.get(f"/article/{aid}/content").get_data(as_text=True)
    assert "aside-block" not in data
    assert "Second paragraph" in data


def test_stored_llm_spans_are_applied(client, app):
    from app import content_filter as cf
    from app.db import get_db_direct
    recap = "Last month the mayor resigned in a separate scandal."
    aid = _padded_article(app, body=f"Today the council met.\n{recap}\nThe vote passed.")
    with app.app_context():
        db = get_db_direct()
        db.execute(text("UPDATE articles SET aside_spans=CAST(:s AS jsonb) WHERE id=:id"),
                   {"s": cf.dump_spans([(cf.fingerprint(recap), cf.KIND_OLDER)]), "id": aid})
        db.commit()
        db.close()
    _set_filter(app, "highlight")
    data = client.get(f"/article/{aid}/content").get_data(as_text=True)
    assert "Older coverage" in data
    assert recap in data


def test_corrupt_aside_spans_degrade_to_pattern_pass(client, app):
    from app.db import get_db_direct
    aid = _padded_article(app)
    with app.app_context():
        db = get_db_direct()
        db.execute(text("UPDATE articles SET aside_spans=CAST(:s AS jsonb) WHERE id=:id"),
                   {"s": '"not-a-list"', "id": aid})
        db.commit()
        db.close()
    _set_filter(app, "remove")
    data = client.get(f"/article/{aid}/content").get_data(as_text=True)
    assert "The council approved the budget" in data   # never a blank reader
    assert "aside-block" in data                        # pass 1 still ran


def test_group_blocks_merges_runs():
    from app.presenters import group_blocks
    groups = group_blocks([
        {"type": "p", "text": "a"},
        {"type": "p", "text": "b", "aside": "promo"},
        {"type": "p", "text": "c", "aside": "promo"},
        {"type": "p", "text": "d"},
    ])
    assert [g["aside"] for g in groups] == [None, "promo", None]
    assert len(groups[1]["blocks"]) == 2
    assert groups[1]["label"] == "Related links" or groups[1]["label"] == "Promotion"


# ── Content filter: settings ───────────────────────────────────────────────────

def test_content_filter_settings_defaults_to_remove(client):
    data = client.get("/settings/content").get_data(as_text=True)
    assert 'value="remove" selected' in data


def test_content_filter_settings_save(client, app):
    r = client.post("/settings/content",
                    data={"content_filter_mode": "highlight", "content_filter_llm": "1"})
    assert b"Saved" in r.data
    from app.db import get_db_direct, get_setting
    with app.app_context():
        db = get_db_direct()
        assert get_setting(db, "content_filter_mode") == "highlight"
        assert get_setting(db, "content_filter_llm") == "1"
        db.close()


def test_content_filter_rejects_unknown_mode(client):
    r = client.post("/settings/content", data={"content_filter_mode": "destroy"})
    assert r.status_code == 400


def test_content_filter_mode_falls_back_on_bad_stored_value(client, app):
    from app.db import get_db_direct, set_setting
    with app.app_context():
        db = get_db_direct()
        set_setting(db, "content_filter_mode", "nonsense")
        db.commit()
        db.close()
    aid = _padded_article(app)
    data = client.get(f"/article/{aid}/content").get_data(as_text=True)
    assert "aside-remove" in data   # default, not a crash


def test_bullet_list_inside_a_rail_is_marked_aside(client, app):
    """A related-stories rail is usually a bulleted list of other headlines."""
    aid = _padded_article(app, body=("The council approved the budget.\n"
                                     "Related\n"
                                     "- Other story one\n"
                                     "- Other story two"))
    _set_filter(app, "highlight")
    data = client.get(f"/article/{aid}/content").get_data(as_text=True)
    assert "aside-highlight" in data
    assert "<li>Other story one</li>" in data
    # The real body must sit outside the aside.
    body_before_aside = data.split("<details")[0]
    assert "The council approved the budget" in body_before_aside


def test_bullet_run_splits_when_a_rail_starts_mid_list():
    """A rail heading inside a list must not drag the real items in with it."""
    from app.presenters import to_blocks
    from app import content_filter as cf
    lines = ["- real one", "- real two", "Related", "- other story"]
    kinds = cf.classify_lines(lines)
    blocks = to_blocks("\n".join(lines), aside_kinds=kinds)
    uls = [b for b in blocks if b["type"] == "ul"]
    assert len(uls) == 2
    assert uls[0]["items"] == ["real one", "real two"]
    assert "aside" not in uls[0]
    assert uls[1]["items"] == ["other story"]
    assert uls[1]["aside"] == cf.KIND_RELATED


def test_search_survives_backend_failure(client, app, monkeypatch, caplog):
    """A search backend error returns an empty list, not a 500."""
    import logging
    caplog.set_level(logging.WARNING, logger="app.views.reading")
    from app.repo import articles as art_repo
    monkeypatch.setattr(art_repo, "search",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.get("/search?q=anything")
    assert r.status_code == 200
    assert "Search failed" in caplog.text


def test_vote_on_unknown_article_returns_404(client):
    assert client.post("/vote/999999/1").status_code == 404


# ── Dismiss all acts on the list you are actually looking at ──────────────────

def test_dismiss_all_in_the_hidden_view_dismisses_hidden_articles(client, app):
    """It only ever matched 'summarized', so pressing it while viewing Hidden
    dismissed the main list instead and the Hidden count never moved."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        add_article(db, fid, seq=1, guid="vis", title="Visible")
        add_article(db, fid, seq=2, guid="hid", status="hidden", title="Hidden one")
        db.close()

    client.post("/dismiss-all?hidden=1")

    hidden = client.get("/articles?hidden=1").data
    main = client.get("/articles").data
    assert b"dismissed" in hidden, "the hidden article should now be dismissed"
    assert b"Visible" in main and b"summarized dismissed" not in main, \
        "the main list must be left alone"


def test_dismiss_all_respects_the_topic_filter(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        add_article(db, fid, seq=1, guid="a", title="Space one", topics=["space"])
        add_article(db, fid, seq=2, guid="b", title="Other one", topics=["economy"])
        db.close()

    client.post("/dismiss-all?topic=space")

    cards = client.get("/articles").data.decode().split('<div class="article-row ')[1:]
    by_title = {("Space one" if "Space one" in c else "Other one"): c for c in cards}
    assert "dismissed" in by_title["Space one"].split(">")[0]
    assert "dismissed" not in by_title["Other one"].split(">")[0]


def test_the_hidden_count_drops_when_hidden_articles_are_dismissed(client, app):
    """The reported symptom: the number beside Hidden did not change."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        for i in range(3):
            add_article(db, fid, seq=i, guid=f"h{i}", status="hidden")
        db.close()

    assert b">3<" in client.get("/sidebar/feeds").data
    client.post("/dismiss-all?hidden=1")
    assert b">3<" not in client.get("/sidebar/feeds").data


def test_a_topic_view_only_lists_that_topic(client, app):
    """/?topic=x rendered, then refreshList refetched without it."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        add_article(db, fid, seq=1, guid="a", title="Tagged one", topics=["argentina"])
        add_article(db, fid, seq=2, guid="b", title="Untagged one", topics=["space"])
        db.close()
    body = client.get("/articles?topic=argentina").data
    assert b"Tagged one" in body
    assert b"Untagged one" not in body


def test_dismiss_all_in_the_saved_view_only_touches_saved_articles(client, app):
    """Starring keeps an article past retention; dismissing it is still allowed,
    but it must not take the rest of the list with it."""
    from app.db import get_db_direct
    from app.repo.articles import toggle_saved
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        keep = add_article(db, fid, seq=1, guid="s", title="Starred one")
        add_article(db, fid, seq=2, guid="p", title="Plain one")
        toggle_saved(db, ensure_bootstrap_user(db), keep)
        db.commit()
        db.close()

    client.post("/dismiss-all?saved=1")

    cards = client.get("/articles").data.decode().split('<div class="article-row ')[1:]
    by_title = {("Starred one" if "Starred one" in c else "Plain one"): c for c in cards}
    assert "dismissed" in by_title["Starred one"].split(">")[0]
    assert "dismissed" not in by_title["Plain one"].split(">")[0]

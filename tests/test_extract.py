"""Extraction chain and YouTube transcripts.

Both are best-effort by design: every rung degrades to the next, and the
article always ends up with *something* rather than failing.
"""

from unittest.mock import MagicMock, patch

import pytest

from app import extract, youtube
from tests.conftest import add_article, add_feed

LONG = "word " * 100          # comfortably over MIN_USEFUL_CHARS
SHORT = "too short"


def _resp(text):
    r = MagicMock()
    r.text = text
    r.raise_for_status = MagicMock()
    return r


# ── the chain ──────────────────────────────────────────────────────────────────

def test_first_fetch_wins_when_it_works():
    with patch("app.extract.httpx.get", return_value=_resp("<html>x</html>")) as get, \
         patch("app.extract.trafilatura.extract", return_value=LONG):
        text, _, source = extract.extract("https://x.test/a")
    assert source == extract.SOURCE_HTTP
    assert get.call_count == 1
    assert get.call_args.kwargs["headers"]["User-Agent"] == extract.BOT_UA


def test_browser_user_agent_is_tried_when_the_bot_one_gets_a_stub():
    """Plenty of sites serve a stub to anything that looks automated."""
    with patch("app.extract.httpx.get", return_value=_resp("<html>x</html>")) as get, \
         patch("app.extract.trafilatura.extract", side_effect=[SHORT, LONG]):
        text, _, source = extract.extract("https://x.test/a")
    assert source == extract.SOURCE_BROWSER_UA
    assert get.call_count == 2
    second = get.call_args_list[1].kwargs["headers"]
    assert "Mozilla" in second["User-Agent"]
    assert second["Referer"].startswith("https://x.test")


def test_readability_catches_what_trafilatura_misses():
    with patch("app.extract.httpx.get", return_value=_resp("<html>x</html>")), \
         patch("app.extract.trafilatura.extract", return_value=SHORT), \
         patch("app.extract._readability", return_value=LONG):
        _, _, source = extract.extract("https://x.test/a")
    assert source == extract.SOURCE_READABILITY


def test_falls_back_to_feed_content():
    with patch("app.extract.httpx.get", side_effect=OSError("unreachable")):
        text, _, source = extract.extract("https://x.test/a", feed_content="From the feed")
    assert source == extract.SOURCE_FEED_CONTENT
    assert text == "From the feed"


def test_falls_back_to_the_snippet():
    with patch("app.extract.httpx.get", side_effect=OSError("unreachable")):
        text, _, source = extract.extract("https://x.test/a", raw_snippet="Just a blurb")
    assert source == extract.SOURCE_SNIPPET


def test_nothing_available_is_reported_not_raised():
    with patch("app.extract.httpx.get", side_effect=OSError("unreachable")):
        text, _, source = extract.extract("https://x.test/a")
    assert text == "" and source == extract.SOURCE_NONE


def test_feed_content_beats_a_short_extraction():
    """A 200-char blurb is what the old code scored articles on."""
    with patch("app.extract.httpx.get", return_value=_resp("<html>x</html>")), \
         patch("app.extract.trafilatura.extract", return_value=SHORT), \
         patch("app.extract._readability", return_value=""):
        _, _, source = extract.extract("https://x.test/a", feed_content=LONG)
    assert source == extract.SOURCE_FEED_CONTENT


def test_og_image_is_captured():
    html = '<meta property="og:image" content="https://x.test/i.jpg">'
    with patch("app.extract.httpx.get", return_value=_resp(html)), \
         patch("app.extract.trafilatura.extract", return_value=LONG):
        _, image, _ = extract.extract("https://x.test/a")
    assert image == "https://x.test/i.jpg"


def test_http_errors_do_not_escape():
    r = MagicMock()
    r.raise_for_status.side_effect = RuntimeError("403")
    with patch("app.extract.httpx.get", return_value=r):
        _, _, source = extract.extract("https://x.test/a", raw_snippet="s")
    assert source == extract.SOURCE_SNIPPET


def test_readability_extracts_real_html():
    html = ("<html><body><article>" + "<p>Some genuine article prose here.</p>" * 20 +
            "</article></body></html>")
    assert len(extract._readability(html)) > extract.MIN_USEFUL_CHARS


def test_readability_failure_returns_empty_rather_than_raising():
    """Malformed markup is routine; it must not cost the article its summary."""
    import readability
    with patch.object(readability, "Document", side_effect=RuntimeError("bad html")):
        assert extract._readability("<html>") == ""


def test_readability_on_junk_input_is_safe():
    assert isinstance(extract._readability(""), str)


# ── YouTube ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,vid", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s", "dQw4w9WgXcQ"),
])
def test_video_ids_are_recognised(url, vid):
    assert youtube.video_id(url) == vid
    assert youtube.is_youtube(url) is True


@pytest.mark.parametrize("url", [
    "https://example.com/article", "", None, "https://youtube.com/channel/abc",
])
def test_non_video_urls_are_not_youtube(url):
    assert youtube.is_youtube(url) is False


def test_transcript_is_joined_and_capped():
    fake = [{"text": "hello"}, {"text": "world"}]
    with patch.dict("sys.modules", {"youtube_transcript_api": MagicMock()}):
        import sys
        sys.modules["youtube_transcript_api"].YouTubeTranscriptApi.get_transcript \
            .return_value = fake
        out = youtube.transcript("https://youtu.be/dQw4w9WgXcQ")
    assert out == "hello world"


def test_transcript_failure_returns_none():
    """Unofficial API — disabled captions and rate limits are routine."""
    with patch.dict("sys.modules", {"youtube_transcript_api": MagicMock()}):
        import sys
        sys.modules["youtube_transcript_api"].YouTubeTranscriptApi.get_transcript \
            .side_effect = RuntimeError("no captions")
        assert youtube.transcript("https://youtu.be/dQw4w9WgXcQ") is None


def test_transcript_for_a_non_video_is_none():
    assert youtube.transcript("https://example.com/a") is None


# ── pipeline integration ───────────────────────────────────────────────────────

def test_extract_source_is_recorded(db_conn):
    from app.pipeline import summarize_scored_articles
    fid = add_feed(db_conn)
    aid = add_article(db_conn, fid, status="scored", url="https://x.test/a")
    with patch("app.pipeline.extract.extract", return_value=(LONG, None, "http")), \
         patch("app.pipeline.ollama_client.generate", return_value="A summary."):
        summarize_scored_articles(db_conn)
    from sqlalchemy import text
    assert db_conn.execute(text(
        "SELECT extract_source FROM articles WHERE id=:i"), {"i": aid}).scalar() == "http"


def test_youtube_articles_use_the_transcript_prompt(db_conn):
    from app.pipeline import summarize_scored_articles
    fid = add_feed(db_conn)
    add_article(db_conn, fid, status="scored",
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    with patch("app.pipeline.youtube.transcript", return_value="spoken words here"), \
         patch("app.pipeline.ollama_client.generate", return_value="A summary.") as gen:
        summarize_scored_articles(db_conn)
    assert "<transcript>" in gen.call_args.kwargs["prompt"]


def test_youtube_without_captions_falls_back_to_the_normal_chain(db_conn, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="app.pipeline")
    from app.pipeline import summarize_scored_articles
    fid = add_feed(db_conn)
    add_article(db_conn, fid, status="scored",
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                raw_snippet="The description")
    with patch("app.pipeline.youtube.transcript", return_value=None), \
         patch("app.extract.httpx.get", side_effect=OSError("blocked")), \
         patch("app.pipeline.ollama_client.generate", return_value="A summary."):
        summarize_scored_articles(db_conn)
    assert "falling back to the description" in caplog.text


# ── per-feed health ────────────────────────────────────────────────────────────

def test_health_reports_full_text_share(db_conn):
    fid = add_feed(db_conn, title="Good Feed")
    add_article(db_conn, fid, seq=1, guid="a", extract_source="http")
    add_article(db_conn, fid, seq=2, guid="b", extract_source="snippet")
    row = {r["feed"]: r for r in extract.health_by_feed(db_conn)}["Good Feed"]
    assert row["measured"] == 2 and row["full_text"] == 1


def test_manage_feeds_flags_a_snippet_only_feed(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db, title="Snippet Feed")
        for i in range(3):
            add_article(db, fid, seq=i, guid=f"g{i}", extract_source="snippet")
        db.close()
    data = client.get("/feeds").data
    assert b"0% full text" in data
    assert b"mostly snippets" in data


def test_transcript_without_the_library_is_none(monkeypatch):
    """The dependency is optional at runtime; its absence must not raise."""
    import builtins
    real_import = builtins.__import__

    def _no_yta(name, *args, **kwargs):
        if name == "youtube_transcript_api":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_yta)
    assert youtube.transcript("https://youtu.be/dQw4w9WgXcQ") is None

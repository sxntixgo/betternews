from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text


def _add_vote(db, article_id, value):
    """Mirror the route: a vote is user-scoped and snapshots its article."""
    from app.repo.articles import record_vote
    from app.repo.users import ensure_bootstrap_user
    record_vote(db, ensure_bootstrap_user(db), article_id, value)
    db.commit()

from app.feeds import strip_html
from app.pipeline import (
    ollama_base,
    score_new_articles,
    summarize_scored_articles,
    run_pipeline,
    regenerate_preferences,
    _PIPELINE_LOCK,
)
from tests.conftest import add_article, add_feed


# ── strip_html ─────────────────────────────────────────────────────────────────

def test_strip_html_removes_tags():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_strip_html_collapses_whitespace():
    assert strip_html("<p>a\n   b\t c</p>") == "a b c"


def test_strip_html_empty():
    assert strip_html("") == ""


# ── score_new_articles ─────────────────────────────────────────────────────────

@patch("app.pipeline.ollama_client.generate")
def test_score_sets_status_scored(mock_gen, memory_db):
    mock_gen.return_value = {"score": 0.8, "reason": "relevant"}
    feed_id = add_feed(memory_db)
    article_id = add_article(memory_db, feed_id, status="new", summary=None, score=None)

    score_new_articles(memory_db, "I like tech news")

    row = memory_db.execute(text("SELECT score, status FROM articles WHERE id=:p0"), {"p0": article_id}).mappings().first()
    assert row["status"] == "scored"
    assert abs(row["score"] - 0.8) < 0.001


@patch("app.pipeline.ollama_client.generate")
def test_score_below_threshold_sets_hidden(mock_gen, memory_db):
    mock_gen.return_value = {"score": 0.1, "reason": "not relevant"}
    feed_id = add_feed(memory_db)
    article_id = add_article(memory_db, feed_id, status="new")

    score_new_articles(memory_db, "")

    row = memory_db.execute(text("SELECT status FROM articles WHERE id=:p0"), {"p0": article_id}).mappings().first()
    assert row["status"] == "hidden"


@patch("app.pipeline.ollama_client.generate")
def test_score_llm_none_skips_article(mock_gen, memory_db):
    mock_gen.return_value = None
    feed_id = add_feed(memory_db)
    article_id = add_article(memory_db, feed_id, status="new")

    score_new_articles(memory_db, "")

    row = memory_db.execute(text("SELECT status FROM articles WHERE id=:p0"), {"p0": article_id}).mappings().first()
    assert row["status"] == "new"


@patch("app.pipeline.ollama_client.generate")
def test_score_clamps_out_of_range(mock_gen, memory_db):
    mock_gen.return_value = {"score": 1.5, "reason": "high"}
    feed_id = add_feed(memory_db)
    add_article(memory_db, feed_id, status="new")

    score_new_articles(memory_db, "")

    row = memory_db.execute(text("SELECT score FROM articles")).mappings().first()
    assert row["score"] <= 1.0


@patch("app.pipeline.ollama_client.generate")
def test_score_handles_exception(mock_gen, memory_db, caplog):
    mock_gen.side_effect = RuntimeError("boom")
    feed_id = add_feed(memory_db)
    add_article(memory_db, feed_id, status="new")
    score_new_articles(memory_db, "")
    assert "Error scoring article" in caplog.text


@patch("app.pipeline.ollama_client.generate")
def test_score_uses_dynamic_model(mock_gen, memory_db):
    from app.db import set_setting
    mock_gen.return_value = {"score": 0.9, "reason": "ok"}
    set_setting(memory_db, "scoring_model", "custom-model:1b")
    memory_db.commit()
    feed_id = add_feed(memory_db)
    add_article(memory_db, feed_id, status="new")
    score_new_articles(memory_db, "")
    assert mock_gen.call_args.kwargs["model"] == "custom-model:1b"


# ── summarize_scored_articles ──────────────────────────────────────────────────

@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_summarize_sets_status_summarized(mock_gen, mock_fetch, memory_db):
    mock_fetch.return_value = ("Full article text here.", None, "http")
    mock_gen.return_value = "This is the summary."
    feed_id = add_feed(memory_db)
    article_id = add_article(memory_db, feed_id, status="scored")

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT summary, status FROM articles WHERE id=:p0"), {"p0": article_id}).mappings().first()
    assert row["status"] == "summarized"
    assert row["summary"] == "This is the summary."


@patch("app.pipeline.ollama_client.generate")
def test_summarize_uses_the_feed_body_when_the_site_is_unreachable(mock_gen, memory_db):
    """The fallback chain lives in app.extract now; this checks the pipeline
    actually summarizes whatever it hands back."""
    mock_gen.return_value = "OK"
    feed_id = add_feed(memory_db)
    add_article(memory_db, feed_id, status="scored",
                feed_content="Body from feed XML", raw_snippet="snippet")
    with patch("app.extract.httpx.get", side_effect=OSError("unreachable")):
        summarize_scored_articles(memory_db)
    call_prompt = mock_gen.call_args.kwargs.get("prompt") or mock_gen.call_args.args[1]
    assert "Body from feed XML" in call_prompt


@patch("app.pipeline.ollama_client.generate")
def test_summarize_records_the_strategy_that_won(mock_gen, memory_db):
    mock_gen.return_value = "OK"
    feed_id = add_feed(memory_db)
    aid = add_article(memory_db, feed_id, status="scored",
                      feed_content=None, raw_snippet="snippet only")
    with patch("app.extract.httpx.get", side_effect=OSError("unreachable")):
        summarize_scored_articles(memory_db)
    call_prompt = mock_gen.call_args.kwargs.get("prompt") or mock_gen.call_args.args[1]
    assert "snippet only" in call_prompt
    assert memory_db.execute(text(
        "SELECT extract_source FROM articles WHERE id=:i"), {"i": aid}).scalar() == "snippet"


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_summarize_llm_none_skips(mock_gen, mock_fetch, memory_db):
    mock_fetch.return_value = ("text", None, "http")
    mock_gen.return_value = None
    feed_id = add_feed(memory_db)
    article_id = add_article(memory_db, feed_id, status="scored")

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT status FROM articles WHERE id=:p0"), {"p0": article_id}).mappings().first()
    assert row["status"] == "scored"


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_summarize_handles_exception(mock_gen, mock_fetch, memory_db, caplog):
    mock_fetch.side_effect = RuntimeError("boom")
    feed_id = add_feed(memory_db)
    add_article(memory_db, feed_id, status="scored")
    summarize_scored_articles(memory_db)
    assert "Error summarizing article" in caplog.text


# ── run_pipeline + lock ────────────────────────────────────────────────────────

@patch("app.pipeline.score_new_articles")
@patch("app.pipeline.summarize_scored_articles")
def test_run_pipeline_writes_last_run(mock_sum, mock_score, app):
    assert run_pipeline(app) is True
    from app.db import get_db_direct, get_setting
    with app.app_context():
        db = get_db_direct()
        ts = get_setting(db, "last_pipeline_run_at")
        db.close()
    assert ts


def test_run_pipeline_skips_when_locked(app):
    _PIPELINE_LOCK.acquire()
    try:
        assert run_pipeline(app) is False
    finally:
        _PIPELINE_LOCK.release()


# ── regenerate_preferences ─────────────────────────────────────────────────────

@patch("app.pipeline.ollama_client.generate")
def test_regenerate_preferences_writes_profile(mock_gen, app):
    mock_gen.return_value = "You like Rust news."
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        a1 = add_article(db, feed_id, seq=1, guid="g1", title="Rust 2025")
        _add_vote(db, a1, 1)
        db.commit()
        db.close()
    regenerate_preferences(app)
    with app.app_context():
        db = get_db_direct()
        row = db.execute(text("SELECT profile_text FROM preferences ORDER BY user_id LIMIT 1")).mappings().first()
        assert "Rust news" in row["profile_text"]
        db.close()


def test_regenerate_preferences_no_votes_costs_nothing(app):
    """No votes means no reader to build a profile from, and no LLM call.

    The sweep is driven by who has actually voted, so with an empty votes table
    there is nobody to iterate -- which is why this asserts the call count
    rather than a log line the old singleton version emitted."""
    from unittest.mock import patch
    with patch("app.ollama_client.generate") as gen:
        assert regenerate_preferences(app) == 0
    gen.assert_not_called()


def test_regenerating_one_reader_without_votes_says_so(app, caplog):
    """Asking for a specific reader is different: they exist, they just have
    nothing to go on, and the button they pressed should explain itself."""
    import logging
    from unittest.mock import patch
    from app.db import get_db_direct
    from app.repo.users import ensure_bootstrap_user

    with app.app_context():
        db = get_db_direct()
        uid = ensure_bootstrap_user(db)
        db.commit()
        db.close()

    caplog.set_level(logging.INFO, logger="app.pipeline")
    with patch("app.ollama_client.generate") as gen:
        assert regenerate_preferences(app, user_id=uid) == 0
    gen.assert_not_called()
    assert "skipping preference regeneration" in caplog.text


@patch("app.pipeline.ollama_client.generate")
def test_regenerate_preferences_llm_none(mock_gen, app, caplog):
    mock_gen.return_value = None
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        feed_id = add_feed(db)
        a = add_article(db, feed_id)
        _add_vote(db, a, 1)
        db.commit()
        db.close()
    regenerate_preferences(app)
    assert "Preference regeneration failed" in caplog.text





@patch("app.pipeline.ollama_client.generate")
def test_score_uses_per_feed_threshold_override(mock_gen, memory_db):
    """A feed with a lower threshold keeps articles that the global threshold would hide."""
    mock_gen.return_value = {"score": 0.2, "reason": "borderline"}
    feed_id = add_feed(memory_db)
    memory_db.execute(text("UPDATE feeds SET score_threshold=0.1 WHERE id=:p0"), {"p0": feed_id})
    add_article(memory_db, feed_id, status="new")

    score_new_articles(memory_db, "")

    row = memory_db.execute(text("SELECT status FROM articles")).mappings().first()
    assert row["status"] == "scored"  # 0.2 >= per-feed 0.1


@patch("app.pipeline.ollama_client.generate")
def test_score_falls_back_to_global_threshold(mock_gen, memory_db):
    """No per-feed override → uses module SCORE_THRESHOLD (0.35 default)."""
    mock_gen.return_value = {"score": 0.2, "reason": "below default"}
    feed_id = add_feed(memory_db)
    add_article(memory_db, feed_id, status="new")

    score_new_articles(memory_db, "")

    row = memory_db.execute(text("SELECT status FROM articles")).mappings().first()
    assert row["status"] == "hidden"


# ── OG image fallback ─────────────────────────────────────────────────────────







@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_summarize_writes_og_image_when_thumbnail_missing(mock_gen, mock_fetch, memory_db):
    mock_fetch.return_value = ("body text", "https://x/og.jpg", "http")
    mock_gen.return_value = "Summary."
    feed_id = add_feed(memory_db)
    add_article(memory_db, feed_id, status="scored", thumbnail_url=None)

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT thumbnail_url FROM articles")).mappings().first()
    assert row["thumbnail_url"] == "https://x/og.jpg"


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_summarize_keeps_existing_thumbnail(mock_gen, mock_fetch, memory_db):
    mock_fetch.return_value = ("body", "https://og/replacement.jpg", "http")
    mock_gen.return_value = "Summary."
    feed_id = add_feed(memory_db)
    add_article(memory_db, feed_id, status="scored", thumbnail_url="https://orig/thumb.jpg")

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT thumbnail_url FROM articles")).mappings().first()
    assert row["thumbnail_url"] == "https://orig/thumb.jpg"



def test_ollama_base_falls_back_to_env_when_unset(memory_db):
    from app import ollama_client
    assert ollama_base(memory_db) == ollama_client.OLLAMA_BASE


def test_ollama_base_uses_settings_when_set(memory_db):
    from app.db import set_setting
    set_setting(memory_db, "ollama_host", "10.0.10.207")
    set_setting(memory_db, "ollama_port", "11434")
    assert ollama_base(memory_db) == "http://10.0.10.207:11434"


def test_ollama_base_ignores_partial_settings(memory_db):
    from app import ollama_client
    from app.db import set_setting
    set_setting(memory_db, "ollama_host", "10.0.10.207")   # no port
    assert ollama_base(memory_db) == ollama_client.OLLAMA_BASE


def test_ollama_base_falls_back_on_invalid_settings(memory_db, caplog):
    from app import ollama_client
    from app.db import set_setting
    set_setting(memory_db, "ollama_host", "10.0.10.207")
    set_setting(memory_db, "ollama_port", "not-a-port")
    assert ollama_base(memory_db) == ollama_client.OLLAMA_BASE
    assert "Invalid Ollama host/port" in caplog.text


# ── De-clickbait titles ────────────────────────────────────────────────────────

def _enable_declickbait(db):
    from app.db import set_setting
    set_setting(db, "declickbait_enabled", "1")
    db.commit()


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_declickbait_off_uses_plain_prompt_and_leaves_columns_null(
    mock_gen, mock_fetch, memory_db
):
    mock_fetch.return_value = ("Full body.", None, "http")
    mock_gen.return_value = "A summary."
    fid = add_feed(memory_db)
    aid = add_article(memory_db, fid, status="scored", title="Real Headline")

    summarize_scored_articles(memory_db)

    assert mock_gen.call_args.kwargs["expect_json"] is False
    row = memory_db.execute(text("SELECT summary, title, clean_title, title_was_clickbait FROM articles WHERE id=:p0"), {"p0": aid}).mappings().first()
    assert row["summary"] == "A summary."
    assert row["title"] == "Real Headline"
    assert row["clean_title"] is None


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_declickbait_stores_rewrite_without_touching_title(mock_gen, mock_fetch, memory_db):
    mock_fetch.return_value = ("Full body.", None, "http")
    mock_gen.return_value = {
        "summary": "The CEO announced layoffs.",
        "was_clickbait": True,
        "clean_title": "CEO announces 400 layoffs",
    }
    _enable_declickbait(memory_db)
    fid = add_feed(memory_db)
    aid = add_article(memory_db, fid, status="scored",
                      title="You won't BELIEVE what this CEO just said")

    summarize_scored_articles(memory_db)

    assert mock_gen.call_args.kwargs["expect_json"] is True
    row = memory_db.execute(text("SELECT title, clean_title, title_was_clickbait, summary FROM articles WHERE id=:p0"), {"p0": aid}).mappings().first()
    # The original must survive — it backs search and duplicate detection.
    assert row["title"] == "You won't BELIEVE what this CEO just said"
    assert row["clean_title"] == "CEO announces 400 layoffs"
    assert row["title_was_clickbait"] == 1
    assert row["summary"] == "The CEO announced layoffs."


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_declickbait_false_leaves_clean_title_null(mock_gen, mock_fetch, memory_db):
    mock_fetch.return_value = ("Full body.", None, "http")
    mock_gen.return_value = {
        "summary": "A summary.",
        "was_clickbait": False,
        "clean_title": "Ordinary Headline",
    }
    _enable_declickbait(memory_db)
    fid = add_feed(memory_db)
    aid = add_article(memory_db, fid, status="scored", title="Ordinary Headline")

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT clean_title, title_was_clickbait FROM articles WHERE id=:p0"), {"p0": aid}).mappings().first()
    assert row["clean_title"] is None
    assert row["title_was_clickbait"] == 0


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_declickbait_malformed_json_still_produces_summary(mock_gen, mock_fetch, memory_db, caplog):
    """The invariant: losing the rewrite is acceptable, losing the summary is not."""
    mock_fetch.return_value = ("Full body.", None, "http")
    mock_gen.side_effect = [None, "Fallback summary."]   # JSON parse fails, then plain text
    _enable_declickbait(memory_db)
    fid = add_feed(memory_db)
    aid = add_article(memory_db, fid, status="scored", title="Some Headline")

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT status, summary, clean_title FROM articles WHERE id=:p0"), {"p0": aid}).mappings().first()
    assert row["status"] == "summarized"
    assert row["summary"] == "Fallback summary."
    assert row["clean_title"] is None
    assert "retrying with plain summarization" in caplog.text


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_declickbait_json_missing_summary_falls_back(mock_gen, mock_fetch, memory_db):
    mock_fetch.return_value = ("Full body.", None, "http")
    mock_gen.side_effect = [{"was_clickbait": True, "clean_title": "X"}, "Fallback."]
    _enable_declickbait(memory_db)
    fid = add_feed(memory_db)
    aid = add_article(memory_db, fid, status="scored", title="T")

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT summary, clean_title FROM articles WHERE id=:p0"), {"p0": aid}).mappings().first()
    assert row["summary"] == "Fallback."
    assert row["clean_title"] is None


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_declickbait_both_calls_fail_skips_article(mock_gen, mock_fetch, memory_db):
    mock_fetch.return_value = ("Full body.", None, "http")
    mock_gen.side_effect = [None, None]
    _enable_declickbait(memory_db)
    fid = add_feed(memory_db)
    aid = add_article(memory_db, fid, status="scored", title="T")

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT status FROM articles WHERE id=:p0"), {"p0": aid}).mappings().first()
    assert row["status"] == "scored"   # left for the next run


@pytest.mark.parametrize("result,expected", [
    ({"was_clickbait": True, "clean_title": "Better title"}, ("Better title", 1)),
    ({"was_clickbait": False, "clean_title": "Better title"}, (None, 0)),
    ({"was_clickbait": True, "clean_title": ""}, (None, 0)),
    ({"was_clickbait": True, "clean_title": "   "}, (None, 0)),
    ({"was_clickbait": True}, (None, 0)),
    ({"was_clickbait": True, "clean_title": "Original"}, (None, 0)),   # unchanged
    ({"was_clickbait": True, "clean_title": "x" * 500}, (None, 0)),    # implausible
    ({}, (None, 0)),
])
def test_clean_title_from_rejects_unusable_rewrites(result, expected):
    from app.pipeline import _clean_title_from
    assert _clean_title_from(result, "Original") == expected


# ── Content filter pass 2 (LLM aside detection) ────────────────────────────────

def _enable_filter_llm(db):
    from app.db import set_setting
    set_setting(db, "content_filter_llm", "1")
    db.commit()


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_aside_pass_skipped_when_setting_off(mock_gen, mock_fetch, memory_db):
    mock_fetch.return_value = ("One.\nTwo.\nThree.\nFour.", None, "http")
    mock_gen.return_value = "A summary."
    fid = add_feed(memory_db)
    aid = add_article(memory_db, fid, status="scored")

    summarize_scored_articles(memory_db)

    assert mock_gen.call_count == 1        # summarization only
    row = memory_db.execute(text("SELECT aside_spans FROM articles WHERE id=:p0"), {"p0": aid}).mappings().first()
    assert row["aside_spans"] is None


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_aside_pass_stores_fingerprints(mock_gen, mock_fetch, memory_db):
    from app import content_filter as cf
    body = "Today's news.\nLast month's recap.\nMore today.\nEnd."
    mock_fetch.return_value = (body, None, "http")
    mock_gen.side_effect = ["A summary.", {"asides": [{"index": 1, "kind": "older_news"}]}]
    _enable_filter_llm(memory_db)
    fid = add_feed(memory_db)
    aid = add_article(memory_db, fid, status="scored")

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT aside_spans FROM articles WHERE id=:p0"), {"p0": aid}).mappings().first()
    assert cf.load_stored(row["aside_spans"]) == {
        cf.fingerprint("Last month's recap."): cf.KIND_OLDER
    }


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_aside_pass_failure_does_not_lose_the_summary(mock_gen, mock_fetch, memory_db):
    """Pass 2 is best-effort: summarization has already succeeded by then."""
    mock_fetch.return_value = ("One.\nTwo.\nThree.\nFour.", None, "http")
    mock_gen.side_effect = ["A summary.", None]
    _enable_filter_llm(memory_db)
    fid = add_feed(memory_db)
    aid = add_article(memory_db, fid, status="scored")

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT status, summary, aside_spans FROM articles WHERE id=:p0"), {"p0": aid}).mappings().first()
    assert row["status"] == "summarized"
    assert row["summary"] == "A summary."
    assert row["aside_spans"] is None


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_aside_pass_exception_is_swallowed(mock_gen, mock_fetch, memory_db, caplog):
    mock_fetch.return_value = ("One.\nTwo.\nThree.\nFour.", None, "http")
    mock_gen.side_effect = ["A summary.", RuntimeError("boom")]
    _enable_filter_llm(memory_db)
    fid = add_feed(memory_db)
    aid = add_article(memory_db, fid, status="scored")

    summarize_scored_articles(memory_db)

    row = memory_db.execute(text("SELECT status FROM articles WHERE id=:p0"), {"p0": aid}).mappings().first()
    assert row["status"] == "summarized"
    assert "Aside detection failed" in caplog.text


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_aside_pass_skips_very_short_bodies(mock_gen, mock_fetch, memory_db):
    mock_fetch.return_value = ("Only one line.", None, "http")
    mock_gen.return_value = "A summary."
    _enable_filter_llm(memory_db)
    fid = add_feed(memory_db)
    add_article(memory_db, fid, status="scored")

    summarize_scored_articles(memory_db)

    assert mock_gen.call_count == 1   # not worth a call


# ── Cross-process pipeline lock ────────────────────────────────────────────────

def test_advisory_lock_blocks_a_second_process(app):
    """threading.Lock cannot span workers; the advisory lock must."""
    from app.db import get_db_direct
    from app.pipeline import _try_advisory_lock, _advisory_unlock
    with app.app_context():
        a, b = get_db_direct(), get_db_direct()   # two separate sessions
        try:
            assert _try_advisory_lock(a) is True
            assert _try_advisory_lock(b) is False   # would be True with a threading lock
            _advisory_unlock(a)
            a.commit()
            assert _try_advisory_lock(b) is True
            _advisory_unlock(b)
            b.commit()
        finally:
            a.close(); b.close()


@patch("app.pipeline.extract.extract")
@patch("app.pipeline.ollama_client.generate")
def test_run_pipeline_skips_when_another_process_holds_the_lock(
    mock_gen, mock_fetch, app, monkeypatch
):
    from app import pipeline
    monkeypatch.setattr(pipeline, "_try_advisory_lock", lambda db: False)
    assert pipeline.run_pipeline(app) is False
    mock_gen.assert_not_called()


# ── LLM boolean coercion (found live) ──────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False),
    ("true", True), ("True", True), ("TRUE", True),
    # The dangerous ones: a plain `if value` reads these as True.
    ("false", False), ("False", False), ("no", False), ("0", False),
    ("", False), ("null", False), ("none", False),
    (None, False), (1, True), (0, False),
])
def test_llm_bool_handles_what_models_actually_return(value, expected):
    from app.pipeline import llm_bool
    assert llm_bool(value) is expected


def test_string_false_does_not_rewrite_a_clean_headline():
    """llama3.1:8b returns "True"/"False" as strings; the string "False" is
    truthy in Python, which would silently invert the decision."""
    from app.pipeline import _clean_title_from
    result = {"was_clickbait": "False", "clean_title": "A rewrite"}
    assert _clean_title_from(result, "Original headline") == (None, 0)


def test_string_true_does_rewrite():
    from app.pipeline import _clean_title_from
    result = {"was_clickbait": "True", "clean_title": "A rewrite"}
    assert _clean_title_from(result, "Original headline") == ("A rewrite", 1)

"""The empty-list diagnosis.

Each cause needs a different action from the reader, and a blank page for all of
them is how a misconfigured model went unnoticed three times on one install.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import text

from app import llm_config, pipeline_status
from tests.conftest import add_article, add_feed


def _uid(db):
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db)
    db.commit()
    return uid


def _diagnose(db, visible=0, *, probe=(True, "ok", ["llama3.2:3b"])):
    with patch("app.ollama_client.probe", return_value=probe):
        return pipeline_status.diagnose(db, user_id=_uid(db), visible=visible)


# ── nothing wrong ──────────────────────────────────────────────────────────────

def test_a_non_empty_list_is_not_diagnosed(db_conn):
    """The check costs queries; skip it entirely when there is nothing to explain."""
    assert _diagnose(db_conn, visible=5) is None


# ── the ladder, in priority order ──────────────────────────────────────────────

def test_no_feeds(db_conn):
    assert _diagnose(db_conn)["kind"] == "no_feeds"


def test_feeds_but_nothing_fetched(db_conn):
    add_feed(db_conn)
    d = _diagnose(db_conn)
    assert d["kind"] == "not_polled"
    assert d["action"][0] == "Refresh"


def test_ollama_unreachable_is_reported_over_a_missing_model(db_conn):
    """If it cannot be reached, its model list is unknown — do not also claim
    the model is missing."""
    add_article(db_conn, add_feed(db_conn), status="new", score=None)
    d = _diagnose(db_conn, probe=(False, "Connection refused — nothing listening.", []))
    assert d["kind"] == "ollama_unreachable"
    assert "Connection refused" in d["detail"]


def test_a_model_that_is_not_installed_is_named(db_conn):
    """The actual failure on this install, three times over: the configured
    model does not exist, so every call fails and nothing progresses."""
    add_article(db_conn, add_feed(db_conn), status="new", score=None)
    llm_config.set_model(db_conn, "scoring", "llama3.2:3b")
    db_conn.commit()
    d = _diagnose(db_conn, probe=(True, "ok", ["llama3.1:8b", "llama3.2:latest"]))
    assert d["kind"] == "model_missing"
    assert "llama3.2:3b" in d["detail"]
    assert "Relevance scoring" in d["detail"]
    assert "llama3.1:8b" in d["detail"]      # says what IS available


def test_waiting_is_not_reported_as_an_error(db_conn):
    add_article(db_conn, add_feed(db_conn), status="new", score=None)
    d = _diagnose(db_conn)
    assert d["kind"] == "processing"
    assert d["admin_only"] is False


def test_unsummarized_articles_also_count_as_waiting(db_conn):
    add_article(db_conn, add_feed(db_conn), status="scored")
    assert _diagnose(db_conn)["kind"] == "processing"


def test_everything_below_the_threshold(db_conn):
    add_article(db_conn, add_feed(db_conn), status="hidden", score=0.1)
    d = _diagnose(db_conn)
    assert d["kind"] == "all_hidden"
    assert d["action"][1] == "/?hidden=1"


def test_caught_up(db_conn):
    from app.repo.articles import mark_read
    fid = add_feed(db_conn)
    aid = add_article(db_conn, fid, status="summarized")
    mark_read(db_conn, _uid(db_conn), aid)
    db_conn.commit()
    assert _diagnose(db_conn)["kind"] == "caught_up"


def test_pending_articles_outrank_hidden_ones(db_conn):
    """Something still processing may yet appear; hidden ones will not."""
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="a", status="new", score=None)
    add_article(db_conn, fid, seq=2, guid="b", status="hidden", score=0.1)
    assert _diagnose(db_conn)["kind"] == "processing"


# ── counts and last run ────────────────────────────────────────────────────────

def test_counts_by_status(db_conn):
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="a", status="new", score=None)
    add_article(db_conn, fid, seq=2, guid="b", status="hidden", score=0.1)
    c = pipeline_status.counts(db_conn)
    assert c["unscored"] == 1 and c["hidden"] == 1 and c["total"] == 2


def test_last_run_is_none_before_any_run(db_conn):
    assert pipeline_status.last_run(db_conn) is None


def test_last_run_is_reported(db_conn):
    db_conn.execute(text("INSERT INTO pipeline_runs (finished_at, scored_n) "
                         "VALUES (now(), 7)"))
    db_conn.commit()
    assert pipeline_status.last_run(db_conn)["scored_n"] == 7


def test_no_model_problems_when_ollama_is_silent(db_conn):
    """An empty model list means unknown, not 'everything is broken'."""
    assert pipeline_status.model_problems(db_conn, []) == []


# ── rendering ──────────────────────────────────────────────────────────────────

def test_the_list_explains_itself_when_empty(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), status="new", score=None)
        llm_config.set_model(db, "scoring", "ghost:1b")
        db.commit()
        db.close()
    with patch("app.ollama_client.probe", return_value=(True, "ok", ["real:8b"])):
        body = client.get("/articles").get_data(as_text=True)
    assert "not installed" in body
    assert "ghost:1b" in body
    assert "Choose a model" in body


def test_a_plain_user_is_told_to_ask_an_admin(login_as, app):
    """The fixes are all admin-only; a reader should not get a dead link."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), status="new", score=None)
        db.commit()
        db.close()
    c, _ = login_as()
    with patch("app.ollama_client.probe",
               return_value=(False, "Connection refused.", [])):
        body = c.get("/articles").get_data(as_text=True)
    assert "administrator needs to sort this out" in body
    assert 'href="/settings"' not in body


def test_a_populated_list_is_not_diagnosed(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), title="Real Article")
        db.close()
    body = client.get("/articles").get_data(as_text=True)
    assert "Real Article" in body
    assert "empty-state" not in body


def test_page_two_being_empty_is_not_diagnosed(client, app):
    """Reaching the end of the list is not a fault."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db))
        db.close()
    assert "empty-state" not in client.get("/articles?offset=50").get_data(as_text=True)


def test_one_broken_job_reads_as_singular(db_conn):
    from app.db import set_setting
    add_article(db_conn, add_feed(db_conn), status="new", score=None)
    # The other five inherit summary_model, so give them something installed —
    # otherwise every job is broken and the message is correctly plural.
    set_setting(db_conn, "summary_model", "real:8b")
    llm_config.set_model(db_conn, "scoring", "ghost:1b")
    db_conn.commit()
    d = _diagnose(db_conn, probe=(True, "ok", ["real:8b"]))
    assert "Relevance scoring is set to use" in d["detail"]


def test_every_job_broken_is_reported_as_such(db_conn):
    """The state a fresh install lands in: nothing configured, so all six jobs
    fall back to a default model the server does not have."""
    add_article(db_conn, add_feed(db_conn), status="new", score=None)
    d = _diagnose(db_conn, probe=(True, "ok", ["llama3.1:8b"]))
    assert d["kind"] == "model_missing"
    for label in ("Relevance scoring", "Article summaries", "What you missed"):
        assert label in d["detail"]


def test_several_broken_jobs_read_as_a_list(db_conn):
    from app.db import set_setting
    add_article(db_conn, add_feed(db_conn), status="new", score=None)
    set_setting(db_conn, "summary_model", "real:8b")
    llm_config.set_model(db_conn, "scoring", "ghost:1b")
    llm_config.set_model(db_conn, "digest", "ghost:1b")
    db_conn.commit()
    d = _diagnose(db_conn, probe=(True, "ok", ["real:8b"]))
    assert " and " in d["detail"] and " are set to use " in d["detail"]

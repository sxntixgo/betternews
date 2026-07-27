"""The Ollama call log.

Answers "what did the server actually say", which is otherwise only in a log
file on a box you may not be standing next to.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import text

from app import call_log, ollama_client


def _on(db):
    from app.db import set_setting
    set_setting(db, call_log.SETTING, "1")
    db.commit()


def _resp(body="hello", status=200):
    r = MagicMock()
    r.status_code = status
    r.text = body
    r.json.return_value = {"response": body}
    r.raise_for_status = MagicMock()
    return r


def _http_error(code, body):
    r = MagicMock()
    r.status_code = code
    r.text = body
    r.raise_for_status.side_effect = httpx.HTTPStatusError(
        "e", request=MagicMock(), response=r)
    return r


# ── opt-in ─────────────────────────────────────────────────────────────────────

def test_logging_is_off_by_default(db_conn):
    assert call_log.enabled(db_conn) is False


def test_nothing_is_recorded_while_off(db_conn, app):
    with patch("app.ollama_client.httpx.post", return_value=_resp()):
        ollama_client.generate("m", "p")
    assert call_log.summary(db_conn)["total"] == 0


# ── recording ──────────────────────────────────────────────────────────────────

def test_a_successful_call_is_recorded_with_both_sides(db_conn, app):
    _on(db_conn)
    with patch("app.ollama_client.httpx.post", return_value=_resp("the summary")):
        ollama_client.generate("llama3.1:8b", "summarize this please",
                               action="summary")
    row = call_log.recent(db_conn)[0]
    assert row["ok"] is True
    assert row["action"] == "summary"
    assert row["model"] == "llama3.1:8b"
    assert "summarize this please" in row["request_preview"]
    assert "the summary" in row["response_preview"]
    assert row["duration_ms"] is not None


def test_a_missing_model_records_ollamas_own_words(db_conn, app):
    """The case that started this: 0 scored, and the reason only in a log."""
    _on(db_conn)
    body = '{"error":"model \'llama3.2:3b\' not found, try pulling it first"}'
    with patch("app.ollama_client.httpx.post", return_value=_http_error(404, body)):
        ollama_client.generate("llama3.2:3b", "score this", action="scoring")
    row = call_log.recent(db_conn)[0]
    assert row["ok"] is False
    assert row["status_code"] == 404
    assert "not found, try pulling it first" in row["response_preview"]
    assert "not installed" in row["error"]


def test_unparseable_json_records_what_came_back(db_conn, app):
    _on(db_conn)
    with patch("app.ollama_client.httpx.post", return_value=_resp("Sure! Here you go:")):
        assert ollama_client.generate("m", "p", expect_json=True) is None
    row = call_log.recent(db_conn)[0]
    assert row["ok"] is False
    assert "Sure! Here you go:" in row["response_preview"]
    assert "not valid JSON" in row["error"]


@patch("app.ollama_client.time.sleep")
def test_an_unreachable_endpoint_is_recorded(_sleep, db_conn, app):
    _on(db_conn)
    with patch("app.ollama_client.httpx.post", side_effect=httpx.ConnectError("refused")):
        ollama_client.generate("m", "p", base_url="http://nope:1234")
    row = call_log.recent(db_conn)[0]
    assert row["ok"] is False and row["endpoint"] == "http://nope:1234"
    assert "Could not reach" in row["error"]


def test_long_prompts_are_truncated(db_conn, app):
    """Prompts run to thousands of characters; the log is for diagnosis, not
    archival."""
    _on(db_conn)
    with patch("app.ollama_client.httpx.post", return_value=_resp("x" * 9000)):
        ollama_client.generate("m", "y" * 9000)
    row = call_log.recent(db_conn)[0]
    assert len(row["request_preview"]) <= ollama_client.PREVIEW_CHARS
    assert len(row["response_preview"]) <= ollama_client.PREVIEW_CHARS


def test_the_log_is_bounded(db_conn, app):
    """A busy pipeline would otherwise fill the disk with prompts."""
    _on(db_conn)
    original = call_log.KEEP
    call_log.KEEP = 5
    try:
        with patch("app.ollama_client.httpx.post", return_value=_resp()):
            for i in range(9):
                ollama_client.generate("m", f"prompt {i}")
        assert call_log.summary(db_conn)["total"] == 5
    finally:
        call_log.KEEP = original


def test_a_logging_failure_never_breaks_the_call(db_conn, app):
    """Diagnostics must not be able to take down the pipeline."""
    _on(db_conn)
    with patch("app.call_log.get_db_direct", side_effect=RuntimeError("db gone")), \
         patch("app.ollama_client.httpx.post", return_value=_resp("still fine")):
        assert ollama_client.generate("m", "p") == "still fine"


# ── reading it back ────────────────────────────────────────────────────────────

def test_failures_can_be_isolated(db_conn, app):
    _on(db_conn)
    with patch("app.ollama_client.httpx.post", return_value=_resp()):
        ollama_client.generate("m", "good")
    with patch("app.ollama_client.httpx.post", return_value=_http_error(500, "boom")):
        ollama_client.generate("m", "bad")
    assert len(call_log.recent(db_conn)) == 2
    failed = call_log.recent(db_conn, failures_only=True)
    assert len(failed) == 1 and failed[0]["ok"] is False


def test_summary_counts_failures(db_conn, app):
    _on(db_conn)
    with patch("app.ollama_client.httpx.post", return_value=_http_error(404, "nope")):
        ollama_client.generate("m", "p")
    s = call_log.summary(db_conn)
    assert s["total"] == 1 and s["failed"] == 1 and s["newest"] is not None


def test_clearing_empties_it(db_conn, app):
    _on(db_conn)
    with patch("app.ollama_client.httpx.post", return_value=_resp()):
        ollama_client.generate("m", "p")
    assert call_log.clear(db_conn) == 1
    db_conn.commit()
    assert call_log.summary(db_conn)["total"] == 0


# ── the page ───────────────────────────────────────────────────────────────────

def test_the_page_explains_itself_when_empty(client):
    body = client.get("/ollama-log").get_data(as_text=True)
    assert "Logging is off and nothing has been recorded" in body
    assert "Start logging" in body


def test_the_page_shows_both_sides_of_a_failure(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        _on(db)
        db.close()
    with patch("app.ollama_client.httpx.post",
               return_value=_http_error(404, '{"error":"model not found"}')):
        ollama_client.generate("ghost:1b", "score this article", action="scoring")
    body = client.get("/ollama-log").get_data(as_text=True)
    assert "score this article" in body
    assert "model not found" in body
    assert "ghost:1b" in body


def test_toggling_from_the_page(client, app):
    client.post("/ollama-log/toggle", data={"enabled": "1"})
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        assert call_log.enabled(db) is True
        db.close()
    client.post("/ollama-log/toggle", data={})
    with app.app_context():
        db = get_db_direct()
        assert call_log.enabled(db) is False
        db.close()


def test_the_log_is_admin_only(login_as):
    c, _ = login_as()
    assert c.get("/ollama-log").status_code == 403
    assert c.post("/ollama-log/clear").status_code == 403


def test_a_write_failure_is_swallowed_and_rolled_back(db_conn, app):
    """A broken insert must not poison the caller's work, or abort the run."""
    _on(db_conn)
    with patch("app.models.ollama_calls.insert", side_effect=RuntimeError("bad insert")), \
         patch("app.ollama_client.httpx.post", return_value=_resp("fine")):
        assert ollama_client.generate("m", "p") == "fine"
    assert call_log.summary(db_conn)["total"] == 0


def test_no_sink_installed_is_harmless(monkeypatch):
    """ollama_client is usable on its own, without the app wiring it up."""
    monkeypatch.setattr(ollama_client, "_call_sink", None)
    with patch("app.ollama_client.httpx.post", return_value=_resp("ok")):
        assert ollama_client.generate("m", "p") == "ok"


def test_a_sink_that_raises_does_not_break_the_call(monkeypatch):
    monkeypatch.setattr(ollama_client, "_call_sink",
                        lambda rec: (_ for _ in ()).throw(RuntimeError("sink down")))
    with patch("app.ollama_client.httpx.post", return_value=_resp("ok")):
        assert ollama_client.generate("m", "p") == "ok"


def test_clearing_from_the_page(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        _on(db)
        db.close()
    with patch("app.ollama_client.httpx.post", return_value=_resp()):
        ollama_client.generate("m", "p")
    assert client.post("/ollama-log/clear").status_code == 302
    with app.app_context():
        db = get_db_direct()
        assert call_log.summary(db)["total"] == 0
        db.close()

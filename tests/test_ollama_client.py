import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app import ollama_client


def _mock_response(text: str, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {"response": text}
    r.raise_for_status = MagicMock()
    return r


@patch("app.ollama_client.httpx.post")
def test_generate_text_success(mock_post):
    mock_post.return_value = _mock_response("Here is the summary.")
    result = ollama_client.generate("llama3.2:3b", "summarize this")
    assert result == "Here is the summary."


@patch("app.ollama_client.httpx.post")
def test_generate_json_success(mock_post):
    payload = {"score": 0.8, "reason": "relevant"}
    mock_post.return_value = _mock_response(json.dumps(payload))
    result = ollama_client.generate("llama3.2:3b", "score this", expect_json=True)
    assert result == payload


@patch("app.ollama_client.httpx.post")
def test_generate_json_invalid_returns_none(mock_post):
    mock_post.return_value = _mock_response("not json at all")
    result = ollama_client.generate("llama3.2:3b", "score this", expect_json=True)
    assert result is None


@patch("app.ollama_client.httpx.post")
def test_generate_json_non_dict_returns_none(mock_post):
    mock_post.return_value = _mock_response("[1, 2, 3]")
    result = ollama_client.generate("llama3.2:3b", "score this", expect_json=True)
    assert result is None


@patch("app.ollama_client.time.sleep")
@patch("app.ollama_client.httpx.post")
def test_generate_retries_on_connect_error(mock_post, mock_sleep):
    mock_post.side_effect = [
        httpx.ConnectError("refused"),
        httpx.ConnectError("refused"),
        _mock_response("ok"),
    ]
    result = ollama_client.generate("llama3.2:3b", "test")
    assert result == "ok"
    assert mock_sleep.call_count == 2


@patch("app.ollama_client.time.sleep")
@patch("app.ollama_client.httpx.post")
def test_generate_exhausts_retries(mock_post, mock_sleep):
    mock_post.side_effect = httpx.ConnectError("refused")
    result = ollama_client.generate("llama3.2:3b", "test")
    assert result is None
    assert mock_post.call_count == ollama_client.MAX_RETRIES


@patch("app.ollama_client.time.sleep")
@patch("app.ollama_client.httpx.post")
def test_generate_retries_on_timeout(mock_post, mock_sleep):
    mock_post.side_effect = [
        httpx.TimeoutException("slow"),
        _mock_response("done"),
    ]
    assert ollama_client.generate("m", "p") == "done"


@patch("app.ollama_client.httpx.post")
def test_generate_http_error_returns_none(mock_post):
    r = MagicMock()
    r.status_code = 500
    r.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error", request=MagicMock(), response=r
    )
    mock_post.return_value = r
    result = ollama_client.generate("llama3.2:3b", "test")
    assert result is None


@patch("app.ollama_client.httpx.post")
def test_generate_unexpected_error_returns_none(mock_post):
    mock_post.side_effect = RuntimeError("???")
    assert ollama_client.generate("m", "p") is None


# ── list_models ────────────────────────────────────────────────────────────────

@patch("app.ollama_client.httpx.get")
def test_list_models_success(mock_get):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5:7b"}]
    }
    mock_get.return_value = resp
    assert ollama_client.list_models() == ["llama3.1:8b", "qwen2.5:7b"]


@patch("app.ollama_client.httpx.get")
def test_list_models_failure_returns_empty(mock_get, caplog):
    mock_get.side_effect = RuntimeError("down")
    assert ollama_client.list_models() == []
    assert "list_models failed" in caplog.text


@patch("app.ollama_client.httpx.get")
def test_list_models_skips_blank_names(mock_get):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"models": [{"name": ""}, {"name": "ok:1"}, {}]}
    mock_get.return_value = resp
    assert ollama_client.list_models() == ["ok:1"]


# ── compose_base_url ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("host,port,expected", [
    ("10.0.10.207", "11434", "http://10.0.10.207:11434"),
    ("  10.0.10.207  ", " 11434 ", "http://10.0.10.207:11434"),
    ("host.docker.internal", 11434, "http://host.docker.internal:11434"),
    ("http://10.0.10.207", "11434", "http://10.0.10.207:11434"),
    ("https://ollama.example.com", "443", "https://ollama.example.com:443"),
    ("http://10.0.10.207/", "11434", "http://10.0.10.207:11434"),
    ("http://10.0.10.207/api", "11434", "http://10.0.10.207:11434"),
])
def test_compose_base_url_accepts(host, port, expected):
    assert ollama_client.compose_base_url(host, port) == expected


@pytest.mark.parametrize("host,port,fragment", [
    ("", "11434", "Host is required"),
    ("   ", "11434", "Host is required"),
    ("10.0.10.207:11434", "11434", "without a port"),
    ("has space", "11434", "not a valid hostname"),
    ("ftp://10.0.10.207", "11434", "Unsupported scheme"),
    ("10.0.10.207", "", "Port must be a number"),
    ("10.0.10.207", "abc", "Port must be a number"),
    ("10.0.10.207", "0", "between 1 and 65535"),
    ("10.0.10.207", "70000", "between 1 and 65535"),
    ("10.0.10.207", "-1", "between 1 and 65535"),
])
def test_compose_base_url_rejects(host, port, fragment):
    with pytest.raises(ValueError) as exc:
        ollama_client.compose_base_url(host, port)
    assert fragment in str(exc.value)


# ── base_url override ──────────────────────────────────────────────────────────

@patch("app.ollama_client.httpx.post")
def test_generate_uses_base_url_override(mock_post):
    mock_post.return_value = _mock_response("ok")
    ollama_client.generate("m", "p", base_url="http://1.2.3.4:9999")
    assert mock_post.call_args[0][0] == "http://1.2.3.4:9999/api/generate"


@patch("app.ollama_client.httpx.post")
def test_generate_falls_back_to_env_base(mock_post):
    mock_post.return_value = _mock_response("ok")
    ollama_client.generate("m", "p")
    assert mock_post.call_args[0][0] == f"{ollama_client.OLLAMA_BASE}/api/generate"


@patch("app.ollama_client.httpx.post")
def test_generate_strips_trailing_slash_from_base(mock_post):
    mock_post.return_value = _mock_response("ok")
    ollama_client.generate("m", "p", base_url="http://1.2.3.4:9999/")
    assert mock_post.call_args[0][0] == "http://1.2.3.4:9999/api/generate"


@patch("app.ollama_client.httpx.get")
def test_list_models_uses_base_url_override(mock_get):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"models": [{"name": "a:1"}]}
    mock_get.return_value = resp
    assert ollama_client.list_models("http://1.2.3.4:9999") == ["a:1"]
    assert mock_get.call_args[0][0] == "http://1.2.3.4:9999/api/tags"


# ── probe ──────────────────────────────────────────────────────────────────────

@patch("app.ollama_client.httpx.get")
def test_probe_success_reports_model_count(mock_get):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"models": [{"name": "a:1"}, {"name": "b:2"}]}
    mock_get.return_value = resp
    ok, message, models = ollama_client.probe("http://1.2.3.4:9999")
    assert ok is True
    assert "2 model(s)" in message
    assert models == ["a:1", "b:2"]


@patch("app.ollama_client.httpx.get")
def test_probe_reachable_but_no_models(mock_get):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"models": []}
    mock_get.return_value = resp
    ok, message, models = ollama_client.probe("http://1.2.3.4:9999")
    assert ok is True
    assert "no models are installed" in message
    assert models == []


@patch("app.ollama_client.httpx.get")
def test_probe_connection_refused(mock_get):
    mock_get.side_effect = httpx.ConnectError("refused")
    ok, message, models = ollama_client.probe("http://1.2.3.4:9999")
    assert ok is False
    assert "Connection refused" in message
    assert "http://1.2.3.4:9999" in message


@patch("app.ollama_client.httpx.get")
def test_probe_timeout(mock_get):
    mock_get.side_effect = httpx.TimeoutException("slow")
    ok, message, _ = ollama_client.probe("http://1.2.3.4:9999")
    assert ok is False
    assert "Timed out" in message


@patch("app.ollama_client.httpx.get")
def test_probe_http_error(mock_get):
    resp = MagicMock()
    resp.status_code = 404
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "nope", request=MagicMock(), response=resp
    )
    mock_get.return_value = resp
    ok, message, _ = ollama_client.probe("http://1.2.3.4:9999")
    assert ok is False
    assert "HTTP 404" in message


@patch("app.ollama_client.httpx.get")
def test_probe_unexpected_error(mock_get):
    mock_get.side_effect = RuntimeError("boom")
    ok, message, _ = ollama_client.probe("http://1.2.3.4:9999")
    assert ok is False
    assert "RuntimeError" in message

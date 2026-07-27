import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app import ollama_client


def _mock_response(text: str, status: int = 200, thinking: str | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    body = {"response": text}
    if thinking is not None:
        body["thinking"] = thinking
    r.json.return_value = body
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


# ── redirects ──────────────────────────────────────────────────────────────────

@patch("app.ollama_client.httpx.post")
def test_generate_follows_redirects(mock_post):
    """A reverse proxy that redirects HTTP to HTTPS otherwise fails every call
    with a 308 and only a log line to show for it."""
    mock_post.return_value = _mock_response("ok")
    ollama_client.generate("m", "p")
    assert mock_post.call_args.kwargs["follow_redirects"] is True


@patch("app.ollama_client.httpx.get")
def test_list_models_follows_redirects(mock_get):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"models": []}
    mock_get.return_value = resp
    ollama_client.list_models()
    assert mock_get.call_args.kwargs["follow_redirects"] is True


# ── failure reporting ──────────────────────────────────────────────────────────

def _http_error(code, body=""):
    resp = MagicMock()
    resp.status_code = code
    resp.text = body
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "err", request=MagicMock(), response=resp)
    return resp


@patch("app.ollama_client.httpx.post")
def test_a_missing_model_says_so_and_quotes_ollama(mock_post):
    """404 is what Ollama returns for a model it does not have — the single most
    common cause of a pipeline that runs and achieves nothing."""
    ollama_client.clear_last_error()
    mock_post.return_value = _http_error(404, '{"error":"model ghost:1b not found"}')
    assert ollama_client.generate("ghost:1b", "p") is None
    err = ollama_client.last_error
    assert "not installed" in err["message"]
    assert "ghost:1b" in err["message"]
    assert "not found" in err["message"]        # Ollama's own words
    assert err["model"] == "ghost:1b"


@patch("app.ollama_client.httpx.post")
def test_other_http_errors_are_reported_with_the_body(mock_post):
    ollama_client.clear_last_error()
    mock_post.return_value = _http_error(502, "upstream gone")
    ollama_client.generate("m", "p")
    assert "HTTP 502" in ollama_client.last_error["message"]
    assert "upstream gone" in ollama_client.last_error["message"]


@patch("app.ollama_client.time.sleep")
@patch("app.ollama_client.httpx.post")
def test_an_unreachable_endpoint_is_reported(mock_post, _sleep):
    ollama_client.clear_last_error()
    mock_post.side_effect = httpx.ConnectError("refused")
    ollama_client.generate("m", "p", base_url="http://nope:1234")
    assert "Could not reach" in ollama_client.last_error["message"]
    assert ollama_client.last_error["endpoint"] == "http://nope:1234"


@patch("app.ollama_client.httpx.post")
def test_unparseable_json_is_reported_with_what_came_back(mock_post):
    ollama_client.clear_last_error()
    mock_post.return_value = _mock_response("I am not JSON at all")
    assert ollama_client.generate("m", "p", expect_json=True) is None
    assert "not valid JSON" in ollama_client.last_error["message"]
    assert "I am not JSON" in ollama_client.last_error["message"]


@patch("app.ollama_client.httpx.post")
def test_a_successful_call_clears_the_last_error(mock_post):
    ollama_client._record("stale failure", "m", "u")
    mock_post.return_value = _mock_response("fine")
    ollama_client.generate("m", "p")
    assert ollama_client.last_error is None


# ── JSON buried in prose ───────────────────────────────────────────────────────

REASONING = (
    "We need to score relevance for a reader with no preference profile yet; "
    "neutral at 0.5. The article is about cats watching outside from windows. "
    "None of these topics directly match; maybe health.\n"
    '{"score": 0.5, "reason": "Cats and mental stimulation.", "topics": ["health"]}'
)


@patch("app.ollama_client.httpx.post")
def test_json_after_a_reasoning_preamble_is_recovered(mock_post):
    """format:"json" does not constrain reasoning models — gpt-oss emits its
    chain of thought into the same field, with the answer after it."""
    mock_post.return_value = _mock_response(REASONING)
    out = ollama_client.generate("gpt-oss:20b", "p", expect_json=True)
    assert out["score"] == 0.5
    assert out["topics"] == ["health"]


@pytest.mark.parametrize("wrapper", [
    '```json\n{"score": 0.8}\n```',
    '```\n{"score": 0.8}\n```',
    'Here is the JSON:\n{"score": 0.8}',
    '{"score": 0.8}\n\nHope that helps!',
    '  \n {"score": 0.8}  \n ',
])
@patch("app.ollama_client.httpx.post")
def test_common_wrappers_are_stripped(mock_post, wrapper):
    mock_post.return_value = _mock_response(wrapper)
    assert ollama_client.generate("m", "p", expect_json=True)["score"] == 0.8


@patch("app.ollama_client.httpx.post")
def test_the_last_object_wins_when_reasoning_contains_braces(mock_post):
    """Reasoning often quotes the schema it was asked for; the real answer is
    the one at the end."""
    text = ('Thinking: the format is {"score": 0.0, "reason": "..."} so I will '
            'fill it in.\n{"score": 0.9, "reason": "actually relevant"}')
    mock_post.return_value = _mock_response(text)
    out = ollama_client.generate("m", "p", expect_json=True)
    assert out["score"] == 0.9
    assert out["reason"] == "actually relevant"


@patch("app.ollama_client.httpx.post")
def test_braces_inside_strings_do_not_confuse_the_scan(mock_post):
    mock_post.return_value = _mock_response('{"reason": "he said {not json} loudly", "score": 0.4}')
    assert ollama_client.generate("m", "p", expect_json=True)["score"] == 0.4


@patch("app.ollama_client.httpx.post")
def test_escaped_quotes_inside_strings_are_handled(mock_post):
    mock_post.return_value = _mock_response(r'{"reason": "she said \"hi\"", "score": 0.2}')
    assert ollama_client.generate("m", "p", expect_json=True)["score"] == 0.2


@pytest.mark.parametrize("junk", [
    "No JSON here at all.",
    "{ unbalanced",
    "[1, 2, 3]",          # valid JSON, but not an object
    "",
])
@patch("app.ollama_client.httpx.post")
def test_genuinely_unusable_responses_still_fail(mock_post, junk):
    """Recovering JSON from prose must not become 'accept anything'."""
    mock_post.return_value = _mock_response(junk)
    assert ollama_client.generate("m", "p", expect_json=True) is None


# ── previews keep the end ──────────────────────────────────────────────────────

def test_short_text_is_previewed_whole():
    assert ollama_client._preview("short") == "short"
    assert ollama_client._preview(None) is None


def test_a_long_preview_keeps_the_tail():
    """A head-only preview cuts off exactly where a reasoning model puts its
    answer."""
    text = "A" * 5000 + "THE-ANSWER-IS-HERE"
    out = ollama_client._preview(text)
    assert out.startswith("AAA")
    assert "THE-ANSWER-IS-HERE" in out
    assert "characters omitted" in out
    assert len(out) < len(text)


# ── reasoning models ───────────────────────────────────────────────────────────

@patch("app.ollama_client.httpx.post")
def test_structured_calls_ask_the_model_not_to_think(mock_post):
    """Asking for JSON means we want the answer, not the reasoning that
    consumed the whole output budget."""
    mock_post.return_value = _mock_response('{"score": 0.5}')
    ollama_client.generate("m", "p", expect_json=True)
    assert mock_post.call_args.kwargs["json"]["think"] is False


@patch("app.ollama_client.httpx.post")
def test_free_text_calls_do_not_disable_thinking(mock_post):
    """Summaries and digests are prose; reasoning may well improve them."""
    mock_post.return_value = _mock_response("a summary")
    ollama_client.generate("m", "p")
    assert "think" not in mock_post.call_args.kwargs["json"]


@patch("app.ollama_client.httpx.post")
def test_a_server_that_rejects_think_is_retried_without_it(mock_post):
    """Older Ollama, or a model with no thinking mode, must not be reported as
    a failure we caused."""
    bad = MagicMock()
    bad.status_code = 400
    bad.text = '{"error":"model does not support think"}'
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        "e", request=MagicMock(), response=bad)
    mock_post.side_effect = [bad, _mock_response('{"score": 0.7}')]
    assert ollama_client.generate("m", "p", expect_json=True)["score"] == 0.7
    assert "think" not in mock_post.call_args_list[1].kwargs["json"]


@patch("app.ollama_client.httpx.post")
def test_json_found_in_the_thinking_field_is_used(mock_post):
    """gpt-oss returns its reasoning separately; when it uses the whole budget
    there, `response` comes back empty."""
    mock_post.return_value = _mock_response(
        "", thinking='Let me think... {"score": 0.4, "reason": "ok"}')
    out = ollama_client.generate("m", "p", expect_json=True)
    assert out["score"] == 0.4


@patch("app.ollama_client.httpx.post")
def test_response_wins_over_thinking(mock_post):
    mock_post.return_value = _mock_response(
        '{"score": 0.9}', thinking='{"score": 0.1}')
    assert ollama_client.generate("m", "p", expect_json=True)["score"] == 0.9


@patch("app.ollama_client.httpx.post")
def test_an_empty_response_says_so_and_suggests_a_fix(mock_post):
    """The reported symptom: HTTP 200, 470 ms, no response body."""
    ollama_client.clear_last_error()
    mock_post.return_value = _mock_response("")
    assert ollama_client.generate("gpt-oss:20b", "p", expect_json=True) is None
    msg = ollama_client.last_error["message"]
    assert "empty response" in msg
    assert "non-reasoning model" in msg
    assert "gpt-oss:20b" in msg


@patch("app.ollama_client.httpx.post")
def test_reasoning_with_no_answer_says_so(mock_post):
    ollama_client.clear_last_error()
    mock_post.return_value = _mock_response(
        "", thinking="We need to consider each article and decide, but ")
    assert ollama_client.generate("gpt-oss:20b", "p", expect_json=True) is None
    msg = ollama_client.last_error["message"]
    assert "only reasoning" in msg
    assert "We need to consider" in msg      # quotes what it actually said

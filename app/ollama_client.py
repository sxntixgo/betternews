import json
import logging
import os
import re
import time

import httpx

log = logging.getLogger(__name__)

OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
DEFAULT_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "180"))
MAX_RETRIES = 3
_RETRY_BACKOFF = [1, 3, 7]

# Why the last call failed, so the UI can say rather than leaving it in a log.
# The pipeline is serialized by an advisory lock and runs in one process, so a
# module-level record is accurate for the run that just happened.
last_error: dict | None = None


def _record(message: str, model: str, base: str) -> None:
    global last_error
    last_error = {"message": message, "model": model, "endpoint": base}
    log.error("Ollama call failed (%s at %s): %s", model, base, message)


def clear_last_error() -> None:
    global last_error
    last_error = None


# Where to send a record of each call. The web and worker run as separate
# processes, so an in-memory buffer would be invisible to whichever one serves
# the page — the sink writes to the database instead. Installed by create_app.
_call_sink = None

PREVIEW_CHARS = 1500
# Reasoning models put the answer *after* the reasoning, so a head-only preview
# truncates the one part worth reading.
PREVIEW_TAIL_CHARS = 600


def _preview(text: str | None) -> str | None:
    if text is None:
        return None
    if len(text) <= PREVIEW_CHARS:
        return text
    head = text[:PREVIEW_CHARS - PREVIEW_TAIL_CHARS]
    tail = text[-PREVIEW_TAIL_CHARS:]
    cut = len(text) - len(head) - len(tail)
    return f"{head}\n\n... [{cut} characters omitted] ...\n\n{tail}"


def set_call_sink(fn) -> None:
    global _call_sink
    _call_sink = fn


def _emit(**record) -> None:
    if _call_sink is None:
        return
    try:
        _call_sink(record)
    except Exception as exc:                      # never let logging break a call
        log.debug("Could not record the Ollama call: %s", exc)

# Hostname or IPv4 literal. Deliberately excludes ':' so a host carrying its own
# port is rejected with a useful message instead of silently losing the port.
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


def compose_base_url(host: str, port: str | int) -> str:
    """Build an Ollama base URL from user-supplied host and port.

    Forgiving about the shapes people actually paste (a full URL, a trailing
    slash, extra whitespace) but strict about the result. Raises ValueError with
    a message intended to be shown in the UI.
    """
    raw = (host or "").strip()
    if not raw:
        raise ValueError("Host is required.")

    scheme = "http"
    if "://" in raw:
        scheme, _, raw = raw.partition("://")
        scheme = scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError(f"Unsupported scheme '{scheme}://' — use http or https.")

    raw = raw.rstrip("/")
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if ":" in raw:
        raise ValueError("Enter the host without a port — use the Port field.")
    if not _HOST_RE.match(raw):
        raise ValueError(f"'{raw}' is not a valid hostname or IP address.")

    try:
        port_num = int(str(port).strip())
    except (TypeError, ValueError):
        raise ValueError("Port must be a number.") from None
    if not 1 <= port_num <= 65535:
        raise ValueError("Port must be between 1 and 65535.")

    return f"{scheme}://{raw}:{port_num}"


def _base(base_url: str | None) -> str:
    """Resolve the endpoint for a call, falling back to the env default."""
    return (base_url or OLLAMA_BASE).rstrip("/")


def generate(
    model: str,
    prompt: str,
    expect_json: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    base_url: str | None = None,
    action: str | None = None,
) -> dict | str | None:
    """Call Ollama /api/generate. Returns dict if expect_json=True, str otherwise, None on failure."""
    payload: dict = {"model": model, "prompt": prompt, "stream": False}
    if expect_json:
        payload["format"] = "json"
        # Reasoning models spend their output budget thinking and often never
        # reach the JSON -- or put it in `thinking` and leave `response` empty.
        # Asking for structured output means we do not want the reasoning.
        # Servers and models that do not support this reject it, so the call is
        # retried once without it rather than failing outright.
        payload["think"] = False

    target = _base(base_url)
    started = time.monotonic()

    def _ms():
        return int((time.monotonic() - started) * 1000)

    for attempt in range(MAX_RETRIES):
        try:
            r = httpx.post(
                f"{_base(base_url)}/api/generate",
                json=payload,
                timeout=timeout,
                # Without this a reverse proxy that redirects to HTTPS returns a
                # 308 and every call fails, with nothing but a log line to say so.
                follow_redirects=True,
            )
            r.raise_for_status()
            body = r.json()
            # A thinking model returns its reasoning separately. When it uses
            # its whole budget reasoning, `response` is empty and the answer,
            # if there is one, is in `thinking`.
            text: str = (body.get("response") or "").strip()
            thinking: str = (body.get("thinking") or "").strip()
            if not text and thinking:
                log.info("Model %s answered only in `thinking` (%d chars)",
                         model, len(thinking))
                text = thinking
            clear_last_error()
            if expect_json:
                parsed = _validate_json(text)
                if parsed is None:
                    if not text:
                        why = (f"Model '{model}' returned an empty response. "
                               f"Reasoning models can spend their whole output "
                               f"budget thinking; try a non-reasoning model for "
                               f"this job.")
                    elif thinking and text is thinking:
                        why = (f"Model '{model}' produced only reasoning and no "
                               f"answer. Try a non-reasoning model for this job. "
                               f"It said: {text[:200]}")
                    else:
                        why = (f"Model returned text that is not valid JSON: "
                               f"{text[:200]}")
                    _record(why, model, target)
                    _emit(action=action, model=model, endpoint=target, ok=False,
                          status_code=r.status_code, duration_ms=_ms(),
                          request_preview=_preview(prompt),
                          response_preview=_preview(text),
                          error=why)
                    return None
                _emit(action=action, model=model, endpoint=target, ok=True,
                      status_code=r.status_code, duration_ms=_ms(),
                      request_preview=_preview(prompt),
                      response_preview=_preview(text), error=None)
                return parsed
            _emit(action=action, model=model, endpoint=target, ok=True,
                  status_code=r.status_code, duration_ms=_ms(),
                  request_preview=_preview(prompt),
                  response_preview=_preview(text), error=None)
            return text
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning("Ollama attempt %d/%d failed: %s", attempt + 1, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES - 1:
                time.sleep(_RETRY_BACKOFF[attempt])
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            body = (exc.response.text or "")[:300].strip()
            if code == 400 and "think" in body.lower() and "think" in payload:
                # Older Ollama, or a model with no thinking mode. Drop it and
                # try again rather than reporting a failure we caused.
                log.info("Server rejected `think`; retrying without it")
                payload.pop("think", None)
                continue
            if code == 404:
                # What Ollama says when the model is not pulled.
                hint = (f"Model '{model}' is not installed on this server. "
                        f"Ollama replied: {body}")
            else:
                hint = f"HTTP {code} from the endpoint. Response: {body}"
            _record(hint, model, target)
            _emit(action=action, model=model, endpoint=target, ok=False,
                  status_code=code, duration_ms=_ms(),
                  request_preview=_preview(prompt),
                  response_preview=body, error=hint)
            return None
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            _record(msg, model, target)
            _emit(action=action, model=model, endpoint=target, ok=False,
                  status_code=None, duration_ms=_ms(),
                  request_preview=_preview(prompt),
                  response_preview=None, error=msg)
            return None

    msg = f"Could not reach the endpoint after {MAX_RETRIES} attempts."
    _record(msg, model, target)
    _emit(action=action, model=model, endpoint=target, ok=False,
          status_code=None, duration_ms=_ms(),
          request_preview=_preview(prompt), response_preview=None, error=msg)
    return None


def list_models(base_url: str | None = None) -> list[str]:
    """Return installed model names from Ollama /api/tags. Empty list on failure."""
    try:
        return _fetch_models(_base(base_url))
    except Exception as exc:
        log.warning("Ollama list_models failed: %s", exc)
        return []


def probe(base_url: str | None = None) -> tuple[bool, str, list[str]]:
    """Check whether Ollama is reachable, for the Settings 'Test connection' button.

    Returns (ok, message, models). Unlike list_models() this surfaces the failure
    reason rather than swallowing it — an unreachable endpoint that silently
    returns [] is exactly how a broken host goes unnoticed.
    """
    target = _base(base_url)
    try:
        models = _fetch_models(target)
    except httpx.ConnectError:
        return False, f"Connection refused — nothing listening on {target}.", []
    except httpx.TimeoutException:
        return False, f"Timed out reaching {target}.", []
    except httpx.HTTPStatusError as exc:
        return False, f"{target} returned HTTP {exc.response.status_code}.", []
    except Exception as exc:
        return False, f"Could not reach {target}: {type(exc).__name__}: {exc}", []

    if not models:
        return True, f"Reachable, but no models are installed on {target}.", []
    return True, f"Connected to {target} — {len(models)} model(s) installed.", models


def _fetch_models(target: str) -> list[str]:
    r = httpx.get(f"{target}/api/tags", timeout=10, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    return sorted(m["name"] for m in data.get("models", []) if m.get("name"))


def _extract_json_object(text: str) -> str | None:
    """Find a JSON object inside prose.

    `format: "json"` does not constrain reasoning models: gpt-oss and similar
    emit their chain of thought into the same response field, with the answer
    somewhere after it. Markdown fences and "Here is the JSON:" preambles are
    just as common. Scanning for a balanced object recovers all of those.

    Scans from the last opening brace backwards, because the answer follows the
    reasoning rather than preceding it, and the reasoning itself often contains
    braces.
    """
    if not text:
        return None
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    for start in reversed(starts):
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def _validate_json(text: str) -> dict | None:
    stripped = (text or "").strip()
    # Markdown fences are the most common wrapper and cost nothing to remove.
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped,
                          flags=re.IGNORECASE | re.MULTILINE).strip()

    for candidate in (stripped, _extract_json_object(stripped)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data

    log.warning("Ollama JSON parse failed | raw: %.300s", text)
    return None

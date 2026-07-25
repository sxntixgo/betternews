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
) -> dict | str | None:
    """Call Ollama /api/generate. Returns dict if expect_json=True, str otherwise, None on failure."""
    payload: dict = {"model": model, "prompt": prompt, "stream": False}
    if expect_json:
        payload["format"] = "json"

    for attempt in range(MAX_RETRIES):
        try:
            r = httpx.post(
                f"{_base(base_url)}/api/generate",
                json=payload,
                timeout=timeout,
            )
            r.raise_for_status()
            text: str = r.json()["response"].strip()
            if expect_json:
                return _validate_json(text)
            return text
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning("Ollama attempt %d/%d failed: %s", attempt + 1, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES - 1:
                time.sleep(_RETRY_BACKOFF[attempt])
        except httpx.HTTPStatusError as exc:
            log.error("Ollama HTTP error %s: %s", exc.response.status_code, exc)
            return None
        except Exception as exc:
            log.error("Ollama unexpected error: %s", exc)
            return None

    log.error("Ollama: all %d retries exhausted for model=%s", MAX_RETRIES, model)
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
    r = httpx.get(f"{target}/api/tags", timeout=10)
    r.raise_for_status()
    data = r.json()
    return sorted(m["name"] for m in data.get("models", []) if m.get("name"))


def _validate_json(text: str) -> dict | None:
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"expected dict, got {type(data).__name__}")
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("Ollama JSON parse failed: %s | raw: %.300s", exc, text)
        return None

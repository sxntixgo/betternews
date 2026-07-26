"""Detect padding inside article bodies.

Publishers append related-story rails, recaps of older coverage and newsletter
CTAs to keep you scrolling. In the reader these read as part of the article.

Two passes:
  1. deterministic regex over lines — cheap, always on, catches the formulaic
     cases (``Related:``, ``Otras noticias``, pagination markers, promos);
  2. optional LLM classification for the semantic case — a paragraph recapping
     last month's developments looks exactly like a paragraph of the article.

Pass 2 results are stored as *content fingerprints* rather than character
offsets: ``full_text`` is immutable once written, but the line-cleaning and
block-splitting between it and the rendered page are render-time logic that may
change. A hash of the paragraph text survives that; an offset would not.
"""

import hashlib
import json
import logging
import re

log = logging.getLogger(__name__)

KIND_RELATED = "related_links"
KIND_PROMO = "promo"
KIND_OLDER = "older_news"

LABELS = {
    KIND_RELATED: "Related links",
    KIND_PROMO: "Promotion",
    KIND_OLDER: "Older coverage",
}

MODE_OFF = "off"
MODE_HIGHLIGHT = "highlight"
MODE_REMOVE = "remove"
MODES = (MODE_OFF, MODE_HIGHLIGHT, MODE_REMOVE)

# A heading that starts a related-stories rail. These run to the end of the body,
# so a match marks everything from there on.
#
# Only genuine *section boundaries* belong here. Promotional one-liners
# (newsletter CTAs, ad markers) live in _PROMO_RE below and are marked
# individually — they routinely appear mid-article, and treating one as a
# boundary would discard the real reporting after it.
_SECTION_RE = re.compile(
    r'^(related\b|more from\b|see also\b|you might\b|read next\b|'
    r'recommended\b|más\s+noticias\b|más\s+información\b|'
    r'también\s+te\s+puede\b|te\s+puede\s+interesar\b|'
    r'otras\s+noticias\b|noticias\s+relacionadas\b|sigue\s+leyendo\b)',
    re.IGNORECASE,
)

# A bare "1" well into the body is a pagination widget, not a sentence.
_PAGINATION_RE = re.compile(r'^-?\s*1\s*$')
_PAGINATION_MIN_WORDS = 80

# Standalone promotional lines, marked individually rather than truncating.
_PROMO_RE = re.compile(
    r'^(this (article|story) was originally published\b|'
    r'este (artículo|contenido) fue publicado originalmente\b|'
    r'sign up\b|subscribe\b|newsletter\b|suscríbete\b|'
    r'advertisement\b|sponsored\b|follow us\b|share this\b|'
    r'copyright\b|all rights reserved\b|todos los derechos reservados\b)',
    re.IGNORECASE,
)

_LINK_ONLY_RE = re.compile(r'^https?://\S+$')


def fingerprint(text: str) -> str:
    """Stable id for a paragraph, tolerant of whitespace and case changes."""
    norm = re.sub(r'\s+', ' ', (text or '').strip().lower())[:200]
    return hashlib.sha1(norm.encode('utf-8')).hexdigest()[:16]


def classify_lines(lines: list[str], stored: dict[str, str] | None = None) -> list[str | None]:
    """Return an aside kind (or None) per input line.

    ``stored`` maps fingerprint -> kind, from a previous LLM pass.
    """
    stored = stored or {}
    kinds: list[str | None] = [None] * len(lines)
    words_seen = 0
    tail_from: int | None = None

    for i, line in enumerate(lines):
        s = line.strip()
        if tail_from is None:
            if _SECTION_RE.match(s):
                tail_from = i
            elif _PAGINATION_RE.match(s) and words_seen > _PAGINATION_MIN_WORDS:
                tail_from = i
        if tail_from is not None:
            kinds[i] = KIND_RELATED
            continue

        if _PROMO_RE.match(s):
            kinds[i] = KIND_PROMO
        elif _LINK_ONLY_RE.match(s):
            kinds[i] = KIND_RELATED
        elif stored:
            hit = stored.get(fingerprint(s))
            if hit:
                kinds[i] = hit
        words_seen += len(s.split())

    return kinds


def load_stored(raw) -> dict[str, str]:
    """Normalize persisted aside_spans. Never raises — bad data means no LLM
    asides, degrading to pass-1-only rather than a broken reader.

    Accepts either a JSON string or the already-decoded value psycopg hands
    back for a jsonb column.
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        if not isinstance(data, list):
            return {}
        out = {}
        for item in data:
            if isinstance(item, dict) and item.get("h") and item.get("kind") in LABELS:
                out[str(item["h"])] = str(item["kind"])
        return out
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("Ignoring unparseable aside_spans: %s", exc)
        return {}


def dump_spans(pairs: list[tuple[str, str]]) -> str | None:
    """Serialize (fingerprint, kind) pairs for storage."""
    if not pairs:
        return None
    return json.dumps([{"h": h, "kind": k} for h, k in pairs], separators=(",", ":"))


def spans_from_llm(result: dict, paragraphs: list[str]) -> list[tuple[str, str]]:
    """Turn an LLM ``{"asides":[{"index":n,"kind":"..."}]}`` reply into
    fingerprint pairs. Unknown kinds, bad indices and malformed rows are dropped
    individually rather than discarding the whole response."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    items = result.get("asides") if isinstance(result, dict) else None
    if not isinstance(items, list):
        return []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        kind = str(item.get("kind") or KIND_OLDER)
        if kind not in LABELS:
            kind = KIND_OLDER
        if not 0 <= idx < len(paragraphs):
            continue
        h = fingerprint(paragraphs[idx])
        if h not in seen:
            seen.add(h)
            pairs.append((h, kind))
    return pairs

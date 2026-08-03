"""What the reader sees, decided once for every client.

These are not formatters. They make the editorial decisions: which headline
shows after de-clickbait, which passages fold away as older-news padding, what
the reading-time estimate is. Rendering them into HTML is a separate job that
belongs to the templates.

The split matters because a second client is coming. While these lived as
private helpers of the view layer, a mobile app could only reimplement them --
and drift, so the phone shows a clickbait headline the web hid -- or take raw
database rows and render something different. Here, both clients call the same
code and agree by construction.

Nothing in this module may import Flask or touch a request context; a client
that is not a browser has neither. `tests/test_presenters.py` enforces that.
Settings are read through `db`, which is passed in.
"""

import re

from app import content_filter
from app.db import get_setting

_READ_TIME_RE = re.compile(
    r'-?\s*(\d+)\s*min(?:uto)?s?\s*(?:de\s+)?(?:read(?:ing)?|lectura)'
    r'|lectura\s*[:\-]?\s*\d+\s*min'
    r'|tiempo\s+de\s+lectura\b',
    re.IGNORECASE,
)

_BULLET_RE = re.compile(r'^[-*•‣◦∙·–—]\s+(.+)$')

# Detect a line that is *only* a tweet permalink — `(?:www\.|mobile\.)?` covers
# both bare `twitter.com` and the `www.` / `mobile.` variants; `x.com` is the
# rebranded host. Matches plain text URLs left over after trafilatura strips
# `<blockquote class="twitter-tweet">` wrappers down to text.
_TWITTER_URL_RE = re.compile(
    r'^https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/'
    r'[A-Za-z0-9_]+/status/\d+(?:\?[^\s]*)?/?$',
    re.IGNORECASE,
)
_INSTAGRAM_URL_RE = re.compile(
    r'^https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/'
    r'[A-Za-z0-9_-]+/?(?:\?[^\s]*)?$',
    re.IGNORECASE,
)


def embed_match(line: str) -> tuple[str, str] | None:
    if _TWITTER_URL_RE.match(line):
        return ("twitter", line)
    if _INSTAGRAM_URL_RE.match(line):
        return ("instagram", line)
    return None


def extract_reading_time(text: str) -> str | None:
    m = _READ_TIME_RE.search(text or "")
    if not m:
        return None
    num = re.search(r'\d+', m.group(0))
    return num.group(0) if num else None


def clean_content(text: str, title: str = "", description: str = "") -> str:
    """Drop reading-time furniture and a leading line duplicating the title.

    Related-story rails and pagination markers used to be *deleted* here. They
    are now classified as asides by `content_filter` instead, so the reader can
    frame them or hide them recoverably rather than silently truncating the
    body. See `content_blocks`.
    """
    cleaned = []
    title_norm = (title or "").strip().lower()
    desc_norm = (description or "").strip().lower()[:120]
    for line in text.split('\n'):
        s = line.strip()
        if not s:
            continue
        if _READ_TIME_RE.search(s):
            continue
        s_norm = s.lower()
        # Skip a leading line that duplicates the title or description
        if not cleaned and title_norm and (s_norm == title_norm or s_norm.startswith(title_norm)):
            continue
        if not cleaned and desc_norm and s_norm.startswith(desc_norm[:60]):
            continue
        cleaned.append(s)
    return '\n'.join(cleaned)


def to_blocks(text: str,
              aside_kinds: list[str | None] | None = None) -> list[dict]:
    """Group consecutive bullet-prefixed lines into list blocks for rendering.

    Lines starting with ``-``, ``*``, ``•`` (and similar marks) followed by a
    space are turned into ``<li>`` items grouped under a single ``<ul>``.

    A line that is *only* a Twitter/X or Instagram permalink becomes an
    ``embed`` block, which the client renders as a card naming the platform.
    This used to be behind an `embeds_enabled` setting, back when the block
    became a `<blockquote>` that the official widget scripts hydrated into a
    real embed. Nothing is fetched from Twitter or Instagram any more, so there
    is nothing left to opt out of -- and the setting had become a no-op that
    still claimed otherwise.

    ``aside_kinds`` carries one entry per non-empty line, tagging blocks that
    `content_filter` judged to be padding.
    """
    blocks: list[dict] = []
    current: list[str] | None = None
    idx = -1
    for line in text.split('\n'):
        s = line.strip()
        if not s:
            continue
        idx += 1
        kind = aside_kinds[idx] if aside_kinds and idx < len(aside_kinds) else None
        em = embed_match(s)
        if em:
            current = None
            b = {"type": "embed", "platform": em[0], "url": em[1]}
            if kind:
                b["aside"] = kind
            blocks.append(b)
            continue
        m = _BULLET_RE.match(s)
        # A bullet run is only continued while its aside classification matches,
        # so a rail starting mid-list doesn't drag the real items into the aside.
        if m and current is not None and blocks[-1].get("aside") == kind:
            current.append(m.group(1).strip())
        elif m:
            current = [m.group(1).strip()]
            b = {"type": "ul", "items": current}
            if kind:
                b["aside"] = kind
            blocks.append(b)
        else:
            current = None
            b = {"type": "p", "text": s}
            if kind:
                b["aside"] = kind
            blocks.append(b)
    return blocks


def group_blocks(blocks: list[dict]) -> list[dict]:
    """Collapse consecutive aside blocks into one group.

    A related-stories rail becomes a single foldable item rather than one per
    paragraph. Body blocks pass through in a group of their own.
    """
    groups: list[dict] = []
    for b in blocks:
        kind = b.get("aside")
        if groups and groups[-1]["aside"] == kind:
            groups[-1]["blocks"].append(b)
        else:
            groups.append({
                "aside": kind,
                "label": content_filter.LABELS.get(kind, "Aside") if kind else None,
                "blocks": [b],
            })
    return groups


def content_blocks(text: str, mode: str,
                   stored_asides: str | None = None) -> tuple[list[dict], int]:
    """Grouped blocks for the reader, plus how many were classified as padding.

    In ``off`` mode nothing is classified, so the body renders whole.
    """
    if mode == content_filter.MODE_OFF:
        blocks = to_blocks(text)
        return group_blocks(blocks), 0
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    kinds = content_filter.classify_lines(
        lines, content_filter.load_stored(stored_asides)
    )
    blocks = to_blocks(text, aside_kinds=kinds)
    n = sum(1 for b in blocks if b.get("aside"))
    return group_blocks(blocks), n


def content_filter_mode(db) -> str:
    mode = get_setting(db, "content_filter_mode", content_filter.MODE_REMOVE)
    return mode if mode in content_filter.MODES else content_filter.MODE_REMOVE


def declickbait(db) -> bool:
    return get_setting(db, "declickbait_enabled", "") == "1"


def resolve_title(d: dict, declickbait: bool) -> tuple[str, str | None]:
    """(title to show, original to show beneath — None when unchanged).

    Falls back to the stored title whenever the rewrite is absent or the setting
    is off, so articles summarized before the feature existed render unchanged.
    """
    title = d.get('title') or ''
    if not declickbait:
        return title, None
    clean = (d.get('clean_title') or '').strip()
    if not clean or not d.get('title_was_clickbait') or clean == title:
        return title, None
    return clean, title


def row_to_article(row, declickbait: bool = False) -> dict:
    d = dict(row)
    text = (d.get('full_text_head') or '') + ' ' + (d.get('raw_snippet') or '')
    d['reading_time'] = extract_reading_time(text)
    d['display_title'], d['original_title'] = resolve_title(d, declickbait)
    return d

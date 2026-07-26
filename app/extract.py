"""Article body extraction, as an ordered chain of strategies.

A single fetch with a bot-ish User-Agent fails on plenty of sites, and the old
code treated that as "no content" — so both the summary *and the relevance
score* were built from a 200-character blurb. That is a silent quality tax: the
article looks scored, just badly.

Each rung is tried in order and the winner is recorded on
`articles.extract_source`, which is what makes the failure visible per feed
instead of invisible in aggregate.
"""

import logging
import re

import httpx
import trafilatura

log = logging.getLogger(__name__)

# Below this, extraction is treated as having failed and the next rung is tried.
MIN_USEFUL_CHARS = 200

BOT_UA = "rss-reader/1.0"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SOURCE_HTTP = "http"
SOURCE_BROWSER_UA = "http_browser_ua"
SOURCE_READABILITY = "readability"
SOURCE_FEED_CONTENT = "feed_content"
SOURCE_SNIPPET = "snippet"
SOURCE_YOUTUBE = "youtube_transcript"
SOURCE_NONE = "none"

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


_EMBED_TWITTER_RE = re.compile(
    r'https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/'
    r'[A-Za-z0-9_]+/status/\d+',
    re.IGNORECASE,
)
_EMBED_INSTAGRAM_RE = re.compile(
    r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+/?',
    re.IGNORECASE,
)


def _extract_embed_urls(html: str) -> list[str]:
    """Pull tweet / Instagram permalinks out of raw article HTML in source order.

    Only collects URLs inside ``<blockquote class="twitter-tweet">`` or
    ``<blockquote class="instagram-media">`` markers — the same wrappers the
    official embed scripts hydrate. Avoids matching unrelated tweet links in
    the page chrome (related-articles widgets, footers, sharing buttons).
    """
    found: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        r'<blockquote\b[^>]*class=["\'][^"\']*'
        r'(twitter-tweet|instagram-media)[^"\']*["\'][^>]*>(.*?)</blockquote>',
        html, flags=re.IGNORECASE | re.DOTALL,
    ):
        cls, body = m.group(1).lower(), m.group(2)
        # Instagram stores the permalink on the blockquote itself when present;
        # fall back to scanning the body for both platforms.
        outer = m.group(0)
        candidates: list[str] = []
        if cls == "instagram-media":
            candidates.extend(_EMBED_INSTAGRAM_RE.findall(outer))
            candidates.extend(_EMBED_INSTAGRAM_RE.findall(body))
        else:
            candidates.extend(_EMBED_TWITTER_RE.findall(body))
        for url in candidates:
            url = url.rstrip('/')
            if url not in seen:
                seen.add(url)
                found.append(url)
    return found


def _merge_embed_urls(text: str, urls: list[str]) -> str:
    """Append embed permalinks as standalone-line URLs so the reader can detect
    them. Skip URLs whose tweet/post id already appears in the extracted text
    (e.g. when trafilatura kept the link)."""
    if not urls:
        return text
    additions = [u for u in urls if u not in text]
    if not additions:
        return text
    suffix = "\n".join(additions)
    return f"{text}\n\n{suffix}" if text else suffix


def _fetch(url: str, user_agent: str, referer: str | None = None) -> str | None:
    headers = {"User-Agent": user_agent,
               "Accept": "text/html,application/xhtml+xml"}
    if referer:
        headers["Referer"] = referer
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True, headers=headers)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        log.debug("fetch failed (%s) for %s: %s", user_agent[:20], url, exc)
        return None


def _readability(html: str) -> str:
    """Second extractor with different heuristics — it catches layouts
    trafilatura misses, and vice versa."""
    try:
        from readability import Document
    except ImportError:            # pragma: no cover - dependency always present
        return ""
    try:
        summary_html = Document(html).summary()
        return re.sub(r"<[^>]+>", " ", summary_html or "")
    except Exception as exc:
        log.debug("readability failed: %s", exc)
        return ""


def _clean(text: str | None) -> str:
    return re.sub(r"[ \t]+", " ", (text or "").strip())


def extract(url: str, *, feed_content: str | None = None,
            raw_snippet: str | None = None) -> tuple[str, str | None, str]:
    """Return (text, og_image, source).

    Never raises: an unreachable site degrades down the chain to the feed's own
    snippet rather than failing the article.
    """
    og_image = None
    html = _fetch(url, BOT_UA)

    if html:
        og_image = _og_image(html)
        text = _clean(trafilatura.extract(html))
        if len(text) >= MIN_USEFUL_CHARS:
            return _with_embeds(text, html), og_image, SOURCE_HTTP

    # Some sites serve a stub to anything that looks automated.
    origin = re.sub(r"^(https?://[^/]+).*$", r"\1/", url or "")
    html2 = _fetch(url, BROWSER_UA, referer=origin)
    if html2:
        og_image = og_image or _og_image(html2)
        text = _clean(trafilatura.extract(html2))
        if len(text) >= MIN_USEFUL_CHARS:
            return _with_embeds(text, html2), og_image, SOURCE_BROWSER_UA

    # Different extractor, same HTML — trafilatura and readability fail on
    # different layouts.
    for candidate in (html2, html):
        if candidate:
            text = _clean(_readability(candidate))
            if len(text) >= MIN_USEFUL_CHARS:
                return _with_embeds(text, candidate), og_image, SOURCE_READABILITY

    fc = _clean(feed_content)
    if fc:
        return fc, og_image, SOURCE_FEED_CONTENT
    sn = _clean(raw_snippet)
    if sn:
        return sn, og_image, SOURCE_SNIPPET
    return "", og_image, SOURCE_NONE


def _with_embeds(text: str, html: str) -> str:
    """Re-attach tweet/Instagram permalinks the extractor stripped.

    trafilatura reduces `<blockquote class="twitter-tweet">` to plain text and
    drops the permalink, so the reader loses the embed entirely. Recovering
    them from the raw HTML is what makes the embeds setting work at all.
    """
    return _merge_embed_urls(text, _extract_embed_urls(html))


def _og_image(html: str) -> str | None:
    m = _OG_IMAGE_RE.search(html or "")
    return m.group(1) if m else None


def health_by_feed(db):
    """Per-feed extraction quality, so a feed that yields only snippets is
    visible rather than quietly mediocre."""
    from sqlalchemy import text
    return db.execute(text("""
        SELECT f.id,
               COALESCE(f.title, f.url)                                  AS feed,
               COUNT(a.id) FILTER (WHERE a.extract_source IS NOT NULL)    AS measured,
               COUNT(a.id) FILTER (WHERE a.extract_source IN
                     ('http','http_browser_ua','readability','youtube_transcript'))
                                                                          AS full_text,
               MODE() WITHIN GROUP (ORDER BY a.extract_source)            AS common_source
        FROM feeds f LEFT JOIN articles a ON a.feed_id = f.id
        GROUP BY f.id, f.title, f.url
        ORDER BY COALESCE(f.title, f.url)
    """)).mappings().all()

"""YouTube transcripts.

`youtube.com/feeds/videos.xml?channel_id=…` is one of the most common non-blog
feeds. feedparser ingests it fine, but there is no article body — so scoring and
summarization both run on a one-line description, which is barely a signal.

Best-effort by design. The transcript API is unofficial, rate-limited and breaks
periodically; every failure falls back to the description rather than costing
the article its summary.
"""

import logging
import re

log = logging.getLogger(__name__)

MAX_TRANSCRIPT_CHARS = 12000
LANGUAGES = ("en", "es")

_VIDEO_ID_RES = (
    re.compile(r"[?&]v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/(?:embed|shorts|live)/([A-Za-z0-9_-]{11})"),
)


def video_id(url: str) -> str | None:
    if not url or "youtu" not in url.lower():
        return None
    for rx in _VIDEO_ID_RES:
        m = rx.search(url)
        if m:
            return m.group(1)
    return None


def is_youtube(url: str) -> bool:
    return video_id(url) is not None


def transcript(url: str) -> str | None:
    """Fetch captions, or None. Never raises."""
    vid = video_id(url)
    if not vid:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        log.debug("youtube-transcript-api not installed")
        return None
    try:
        entries = YouTubeTranscriptApi.get_transcript(vid, languages=list(LANGUAGES))
    except Exception as exc:
        # Unofficial API: expect disabled captions, rate limits and outages.
        log.info("No transcript for %s: %s", vid, type(exc).__name__)
        return None
    text = " ".join((e.get("text") or "").strip() for e in entries or [])
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TRANSCRIPT_CHARS] or None

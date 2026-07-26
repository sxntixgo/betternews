import logging
import os
import re
import threading

import httpx
import trafilatura
import flask

from datetime import datetime, timezone

from sqlalchemy import text

from app import content_filter, prompts, ollama_client
from app.db import get_db_direct, get_setting, set_setting

log = logging.getLogger(__name__)

DEFAULT_SCORING_MODEL = os.environ.get("SCORING_MODEL", "llama3.2:3b")
DEFAULT_SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "llama3.2:3b")
SCORE_THRESHOLD = float(os.environ.get("SCORE_THRESHOLD", "0.35"))
SCORING_SNIPPET_CHARS = int(os.environ.get("SCORING_SNIPPET_CHARS", "2000"))

# Process-wide lock — prevents concurrent /poll clicks from running the pipeline
# in parallel and double-summarizing the same scored articles.
_PIPELINE_LOCK = threading.Lock()


def _scoring_model(db) -> str:
    return get_setting(db, "scoring_model", DEFAULT_SCORING_MODEL) or DEFAULT_SCORING_MODEL


def _summary_model(db) -> str:
    return get_setting(db, "summary_model", DEFAULT_SUMMARY_MODEL) or DEFAULT_SUMMARY_MODEL


def ollama_base(db) -> str:
    """Endpoint for Ollama calls: Settings override, else the OLLAMA_HOST env var.

    Read per call rather than cached, so changing it in Settings takes effect on
    the next scheduled job without restarting the container.
    """
    host = (get_setting(db, "ollama_host", "") or "").strip()
    port = (get_setting(db, "ollama_port", "") or "").strip()
    if not (host and port):
        return ollama_client.OLLAMA_BASE
    try:
        return ollama_client.compose_base_url(host, port)
    except ValueError as exc:
        log.warning("Invalid Ollama host/port in settings (%s) — using %s",
                    exc, ollama_client.OLLAMA_BASE)
        return ollama_client.OLLAMA_BASE


def run_pipeline(app: flask.Flask) -> bool:
    """Score new articles then summarize scored ones. Called by APScheduler.

    Returns True if the pipeline ran, False if a previous run was still in
    flight and this call was skipped.
    """
    if not _PIPELINE_LOCK.acquire(blocking=False):
        log.info("Pipeline already running — skipping this trigger")
        return False
    try:
        with app.app_context():
            db = get_db_direct()
            try:
                row = db.execute(text(
                    "SELECT profile_text FROM preferences WHERE id=1"
                )).mappings().first()
                profile_text = row["profile_text"] if row else ""
                score_new_articles(db, profile_text)
                summarize_scored_articles(db)
                set_setting(
                    db,
                    "last_pipeline_run_at",
                    datetime.now(timezone.utc).isoformat(),
                )
                db.commit()
            finally:
                db.close()
        return True
    finally:
        _PIPELINE_LOCK.release()


def score_new_articles(db, profile_text: str) -> None:
    articles = db.execute(text(
        """SELECT a.id, a.title, a.raw_snippet, f.score_threshold
           FROM articles a JOIN feeds f ON f.id = a.feed_id
           WHERE a.status='new' LIMIT 50"""
    )).mappings().all()
    model = _scoring_model(db)
    base_url = ollama_base(db)

    for article in articles:
        try:
            snippet = (article["raw_snippet"] or "")[:SCORING_SNIPPET_CHARS]
            prompt = prompts.scoring_prompt(
                profile_text, article["title"], snippet
            )
            result = ollama_client.generate(
                model=model, prompt=prompt, expect_json=True, base_url=base_url
            )
            if result is None:
                log.warning("Scoring skipped for article id=%d (no LLM response)", article["id"])
                continue

            score = max(0.0, min(1.0, float(result.get("score", 0.5))))
            reason = str(result.get("reason", ""))
            threshold = (
                article["score_threshold"]
                if article["score_threshold"] is not None
                else SCORE_THRESHOLD
            )
            status = "hidden" if score < threshold else "scored"

            db.execute(
                text("UPDATE articles SET score=:score, score_reason=:reason, "
                     "status=:status WHERE id=:id"),
                {"score": score, "reason": reason, "status": status,
                 "id": article["id"]},
            )
            db.commit()
            log.info("Scored article id=%d score=%.2f status=%s", article["id"], score, status)
        except Exception as exc:
            log.error("Error scoring article id=%d: %s", article["id"], exc)


MAX_CLEAN_TITLE_CHARS = 200


def _clean_title_from(result: dict, original: str) -> tuple[str | None, int]:
    """Pull (clean_title, was_clickbait) out of an LLM response, defensively.

    Returns (None, 0) whenever the rewrite shouldn't be shown — not flagged as
    clickbait, empty, unchanged, or implausibly long. The display path treats
    NULL as "use the original", so every rejection degrades to current behaviour.
    """
    if not result.get("was_clickbait"):
        return None, 0
    candidate = str(result.get("clean_title") or "").strip()
    if not candidate or candidate == (original or "").strip():
        return None, 0
    if len(candidate) > MAX_CLEAN_TITLE_CHARS:
        log.warning("Discarding clean_title of %d chars (limit %d)",
                    len(candidate), MAX_CLEAN_TITLE_CHARS)
        return None, 0
    return candidate, 1


def _detect_asides(full_text: str, model: str, base_url: str) -> str | None:
    """Pass 2 of the content filter: ask the LLM which paragraphs are padding.

    Best-effort by design — a failure returns None and the reader falls back to
    the deterministic pass alone. It must never interrupt summarization, which
    has already succeeded by the time this runs.
    """
    paragraphs = [ln.strip() for ln in (full_text or "").split("\n") if ln.strip()]
    if len(paragraphs) < 3:
        return None
    try:
        result = ollama_client.generate(
            model=model,
            prompt=prompts.aside_prompt(paragraphs),
            expect_json=True,
            base_url=base_url,
        )
        if not isinstance(result, dict):
            log.warning("Aside detection returned no usable JSON")
            return None
        return content_filter.dump_spans(
            content_filter.spans_from_llm(result, paragraphs)
        )
    except Exception as exc:
        log.warning("Aside detection failed: %s", exc)
        return None


def summarize_scored_articles(db) -> None:
    articles = db.execute(text(
        "SELECT id, url, title, raw_snippet, feed_content, thumbnail_url "
        "FROM articles WHERE status='scored' LIMIT 20"
    )).mappings().all()
    model = _summary_model(db)
    base_url = ollama_base(db)
    declickbait = get_setting(db, "declickbait_enabled", "") == "1"
    filter_llm = get_setting(db, "content_filter_llm", "") == "1"

    for article in articles:
        try:
            fetched_text, og_image = fetch_full_text_and_image(article["url"])
            full_text = (
                fetched_text
                or (article["feed_content"] if "feed_content" in article.keys() else None)
                or article["raw_snippet"]
                or ""
            )

            summary = None
            clean_title, was_clickbait = None, 0

            if declickbait:
                result = ollama_client.generate(
                    model=model,
                    prompt=prompts.summarization_with_title_prompt(
                        full_text, article["title"]
                    ),
                    expect_json=True,
                    base_url=base_url,
                )
                if isinstance(result, dict) and str(result.get("summary") or "").strip():
                    summary = str(result["summary"]).strip()
                    clean_title, was_clickbait = _clean_title_from(
                        result, article["title"]
                    )
                else:
                    # Losing the summary is worse than losing the rewrite, so
                    # fall back to the plain-text prompt rather than skipping.
                    log.warning(
                        "De-clickbait response unusable for article id=%d — "
                        "retrying with plain summarization", article["id"]
                    )

            if summary is None:
                summary = ollama_client.generate(
                    model=model,
                    prompt=prompts.summarization_prompt(full_text),
                    expect_json=False,
                    base_url=base_url,
                )
            if summary is None:
                log.warning("Summarization skipped for article id=%d", article["id"])
                continue

            aside_spans = None
            if filter_llm:
                aside_spans = _detect_asides(full_text, model, base_url)

            new_thumb = article["thumbnail_url"] or og_image
            db.execute(
                text("UPDATE articles SET full_text=:full_text, summary=:summary, "
                     "thumbnail_url=:thumb, clean_title=:clean_title, "
                     "title_was_clickbait=:was_clickbait, "
                     "aside_spans=CAST(:aside_spans AS jsonb), "
                     "status='summarized' WHERE id=:id"),
                {"full_text": full_text, "summary": summary.strip(),
                 "thumb": new_thumb, "clean_title": clean_title,
                 "was_clickbait": bool(was_clickbait),
                 "aside_spans": aside_spans, "id": article["id"]},
            )
            db.commit()
            log.info("Summarized article id=%d%s", article["id"],
                     " (title de-clickbaited)" if clean_title else "")
        except Exception as exc:
            log.error("Error summarizing article id=%d: %s", article["id"], exc)


def regenerate_preferences(app: flask.Flask) -> None:
    """Rebuild the user preference profile from recent votes. Called by APScheduler."""
    with app.app_context():
        db = get_db_direct()
        try:
            rows = db.execute(text(
                """SELECT value,
                          COALESCE(title_snapshot, '')   AS title,
                          COALESCE(summary_snapshot, '') AS summary
                   FROM votes
                   ORDER BY created_at DESC LIMIT 200"""
            )).mappings().all()

            liked = [
                f"{r['title']}: {r['summary'] or ''}"
                for r in rows if r["value"] == 1
            ]
            disliked = [
                f"{r['title']}: {r['summary'] or ''}"
                for r in rows if r["value"] == -1
            ]

            if not liked and not disliked:
                log.info("No votes yet — skipping preference regeneration")
                return

            prompt = prompts.profile_prompt(liked, disliked)
            new_profile = ollama_client.generate(
                model=_summary_model(db), prompt=prompt, expect_json=False,
                base_url=ollama_base(db),
            )
            if new_profile is None:
                log.error("Preference regeneration failed — LLM returned None")
                return

            db.execute(
                text("""INSERT INTO preferences (id, profile_text, updated_at)
                        VALUES (1, :profile, now())
                        ON CONFLICT (id) DO UPDATE
                        SET profile_text = EXCLUDED.profile_text,
                            updated_at   = EXCLUDED.updated_at"""),
                {"profile": new_profile.strip()},
            )
            db.commit()
            log.info("Preference profile updated (%d chars)", len(new_profile))
        finally:
            db.close()


_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# Tweet permalink: `https://twitter.com/<user>/status/<id>` or the `x.com`
# rebrand. Trafilatura strips the surrounding `<blockquote class="twitter-tweet">`
# down to plain text and drops this anchor entirely, so we have to recover
# permalinks from the raw HTML before extraction.
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


def fetch_full_text(url: str) -> str:
    """Backward-compatible wrapper used by tests/older callers."""
    return fetch_full_text_and_image(url)[0]


def fetch_full_text_and_image(url: str) -> tuple[str, str | None]:
    """Fetch the article URL once and return (extracted_text, og_image_url)."""
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True,
                      headers={"User-Agent": "rss-reader/1.0"})
        r.raise_for_status()
        text = trafilatura.extract(r.text) or ""
        text = _merge_embed_urls(text, _extract_embed_urls(r.text))
        m = _OG_IMAGE_RE.search(r.text)
        og = m.group(1) if m else None
        return text, og
    except Exception as exc:
        log.warning("fetch_full_text failed for %s: %s", url, exc)
        return "", None

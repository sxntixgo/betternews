import logging
import os
import re
import threading

import httpx
import trafilatura
import flask

from datetime import datetime, timezone

from sqlalchemy import text

from app import content_filter, extract, prompts, ollama_client, topics as topics_mod, youtube
from app.db import get_db_direct, get_setting, set_setting

log = logging.getLogger(__name__)

DEFAULT_SCORING_MODEL = os.environ.get("SCORING_MODEL", "llama3.2:3b")
DEFAULT_SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "llama3.2:3b")
SCORE_THRESHOLD = float(os.environ.get("SCORE_THRESHOLD", "0.35"))
SCORING_SNIPPET_CHARS = int(os.environ.get("SCORING_SNIPPET_CHARS", "2000"))
# 1 reproduces the original one-call-per-article behaviour exactly.
SCORING_BATCH_SIZE = max(1, int(os.environ.get("SCORING_BATCH_SIZE", "8")))
HIGH_SCORE_NOTIFY = float(os.environ.get("HIGH_SCORE_NOTIFY", "0.8"))

# Process-wide lock — prevents concurrent /poll clicks within one worker.
_PIPELINE_LOCK = threading.Lock()

# ...and a Postgres advisory lock across workers. A threading.Lock cannot span
# processes, so the moment gunicorn runs more than one worker (which Postgres
# now makes viable) it stops serializing anything. Concurrent pipeline runs
# would double-summarize and contend for the same GPU — see docs/plan.md 598.
_PIPELINE_LOCK_KEY = 0x7B5EAD01


def _try_advisory_lock(db) -> bool:
    return bool(db.execute(
        text("SELECT pg_try_advisory_lock(:k)"), {"k": _PIPELINE_LOCK_KEY}
    ).scalar())


def _advisory_unlock(db) -> None:
    db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _PIPELINE_LOCK_KEY})


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
        log.info("Pipeline already running in this process — skipping")
        return False
    try:
        with app.app_context():
            db = get_db_direct()
            if not _try_advisory_lock(db):
                log.info("Pipeline already running in another process — skipping")
                db.execute(text(
                    "INSERT INTO pipeline_runs (finished_at, skipped) "
                    "VALUES (now(), true)"))
                db.commit()
                db.close()
                return False
            try:
                run_id = db.execute(text(
                    "INSERT INTO pipeline_runs (started_at) VALUES (now()) "
                    "RETURNING id")).scalar()
                db.commit()
                row = db.execute(text(
                    "SELECT profile_text FROM preferences WHERE id=1"
                )).mappings().first()
                profile_text = row["profile_text"] if row else ""
                scored = score_new_articles(db, profile_text)
                summarized = summarize_scored_articles(db)
                db.execute(text(
                    "UPDATE pipeline_runs SET finished_at=now(), scored_n=:s, "
                    "summarized_n=:m WHERE id=:i"),
                    {"s": int(scored or 0), "m": int(summarized or 0), "i": run_id})
                set_setting(
                    db,
                    "last_pipeline_run_at",
                    datetime.now(timezone.utc).isoformat(),
                )
                db.commit()
            finally:
                _advisory_unlock(db)
                db.commit()
                db.close()
        return True
    finally:
        _PIPELINE_LOCK.release()


def score_new_articles(db, profile_text: str) -> int:
    """Score everything waiting. Returns how many were scored."""
    articles = db.execute(text(
        """SELECT a.id, a.title, a.raw_snippet, f.score_threshold
           FROM articles a JOIN feeds f ON f.id = a.feed_id
           WHERE a.status='new' LIMIT 50"""
    )).mappings().all()
    if not articles:
        return 0

    model = _scoring_model(db)
    base_url = ollama_base(db)
    vocab = topics_mod.vocabulary(db)
    rule_map = topics_mod.rules(db)
    try:
        global_threshold = float(get_setting(db, "score_threshold", "") or SCORE_THRESHOLD)
    except ValueError:
        global_threshold = SCORE_THRESHOLD

    scored = 0
    for start in range(0, len(articles), SCORING_BATCH_SIZE):
        chunk = articles[start:start + SCORING_BATCH_SIZE]
        results = None
        if len(chunk) > 1:
            results = _score_batch(chunk, profile_text, model, base_url, vocab)
            if results is None:
                # Batched JSON is the least reliable part of this; never drop
                # articles because of it.
                log.warning("Batch scoring unusable for %d articles — "
                            "falling back to one call each", len(chunk))
        if results is None:
            results = _score_individually(chunk, profile_text, model, base_url, vocab)

        for article in chunk:
            result = results.get(article["id"])
            if result is None:
                log.warning("Scoring skipped for article id=%d (no LLM response)",
                            article["id"])
                continue
            try:
                _persist_score(db, article, result, rule_map, global_threshold)
                scored += 1
            except Exception as exc:
                log.error("Error scoring article id=%d: %s", article["id"], exc)
    return scored


def _score_batch(chunk, profile_text, model, base_url, vocab) -> dict | None:
    """One call for the whole chunk, or None if the reply is unusable."""
    items = [{"id": a["id"],
              "title": a["title"],
              "snippet": (a["raw_snippet"] or "")[:SCORING_SNIPPET_CHARS]}
             for a in chunk]
    try:
        reply = ollama_client.generate(
            model=model,
            prompt=prompts.batch_scoring_prompt(profile_text, items, vocabulary=vocab),
            expect_json=True, base_url=base_url,
        )
    except Exception as exc:
        log.error("Batch scoring call failed: %s", exc)
        return None
    if not isinstance(reply, dict):
        return None
    rows = reply.get("results")
    if not isinstance(rows, list):
        return None

    wanted = {a["id"] for a in chunk}
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            rid = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        if rid in wanted:
            out[rid] = row
    # A partial answer means the model lost track; redo the chunk properly
    # rather than silently leaving articles unscored.
    return out if len(out) == len(wanted) else None


def _score_individually(chunk, profile_text, model, base_url, vocab) -> dict:
    out = {}
    for article in chunk:
        snippet = (article["raw_snippet"] or "")[:SCORING_SNIPPET_CHARS]
        try:
            reply = ollama_client.generate(
                model=model,
                prompt=prompts.scoring_prompt(profile_text, article["title"], snippet,
                                              vocabulary=vocab),
                expect_json=True, base_url=base_url,
            )
        except Exception as exc:
            log.error("Error scoring article id=%d: %s", article["id"], exc)
            continue
        if isinstance(reply, dict):
            out[article["id"]] = reply
    return out


def _persist_score(db, article, result, rule_map, global_threshold) -> None:
    score = max(0.0, min(1.0, float(result.get("score", 0.5))))
    reason = str(result.get("reason", ""))
    article_topics = topics_mod.normalize(result.get("topics"))

    score, muted, note = topics_mod.apply_rules(score, article_topics, rule_map)
    if note:
        reason = f"{note}. {reason}".strip()

    threshold = (article["score_threshold"]
                 if article["score_threshold"] is not None else global_threshold)
    status = "hidden" if (muted or score < threshold) else "scored"

    db.execute(
        text("UPDATE articles SET score=:score, score_reason=:reason, "
             "status=:status, topics=:topics WHERE id=:id"),
        {"score": score, "reason": reason, "status": status,
         "topics": article_topics or None, "id": article["id"]},
    )
    db.commit()
    log.info("Scored article id=%d score=%.2f status=%s", article["id"], score, status)


def _extract_body(article) -> tuple[str, str | None, str]:
    """Body text for an article, plus which strategy produced it.

    YouTube entries carry no body at all, so captions are tried first for them.
    """
    url = article["url"]
    if youtube.is_youtube(url):
        captions = youtube.transcript(url)
        if captions:
            return captions, None, extract.SOURCE_YOUTUBE
        log.info("No transcript for %s — falling back to the description", url)

    feed_content = article["feed_content"] if "feed_content" in article.keys() else None
    return extract.extract(url, feed_content=feed_content,
                           raw_snippet=article["raw_snippet"])


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


MAX_CLEAN_TITLE_CHARS = 200

_FALSEY_STRINGS = {"", "false", "no", "0", "none", "null"}


def llm_bool(value) -> bool:
    """Interpret a boolean from an LLM as a boolean.

    Models return these inconsistently — `true`, `"true"`, `"True"`, `"false"`.
    Python treats the *string* "false" as truthy, so a plain `if value` silently
    inverts the answer. Observed live with llama3.1:8b returning "True".
    """
    if isinstance(value, str):
        return value.strip().lower() not in _FALSEY_STRINGS
    return bool(value)


def _clean_title_from(result: dict, original: str) -> tuple[str | None, int]:
    """Pull (clean_title, was_clickbait) out of an LLM response, defensively.

    Returns (None, 0) whenever the rewrite shouldn't be shown — not flagged as
    clickbait, empty, unchanged, or implausibly long. The display path treats
    NULL as "use the original", so every rejection degrades to current behaviour.
    """
    if not llm_bool(result.get("was_clickbait")):
        return None, 0
    candidate = str(result.get("clean_title") or "").strip()
    if not candidate or candidate == (original or "").strip():
        return None, 0
    if len(candidate) > MAX_CLEAN_TITLE_CHARS:
        log.warning("Discarding clean_title of %d chars (limit %d)",
                    len(candidate), MAX_CLEAN_TITLE_CHARS)
        return None, 0
    return candidate, 1


def summarize_scored_articles(db) -> int:
    articles = db.execute(text(
        "SELECT id, url, title, raw_snippet, feed_content, thumbnail_url "
        "FROM articles WHERE status='scored' LIMIT 20"
    )).mappings().all()
    model = _summary_model(db)
    base_url = ollama_base(db)
    declickbait = get_setting(db, "declickbait_enabled", "") == "1"
    filter_llm = get_setting(db, "content_filter_llm", "") == "1"
    done = 0

    for article in articles:
        try:
            full_text, og_image, source = _extract_body(article)

            summary = None
            clean_title, was_clickbait = None, 0

            if source == extract.SOURCE_YOUTUBE:
                # Spoken text summarizes badly under the article prompt.
                summary = ollama_client.generate(
                    model=model,
                    prompt=prompts.transcript_summarization_prompt(
                        full_text, article["title"]),
                    expect_json=False, base_url=base_url,
                )
            elif declickbait:
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
                     "extract_source=:source, status='summarized' WHERE id=:id"),
                {"full_text": full_text, "summary": summary.strip(),
                 "thumb": new_thumb, "clean_title": clean_title,
                 "was_clickbait": bool(was_clickbait),
                 "aside_spans": aside_spans, "source": source,
                 "id": article["id"]},
            )
            db.commit()
            done += 1
            log.info("Summarized article id=%d%s", article["id"],
                     " (title de-clickbaited)" if clean_title else "")
        except Exception as exc:
            log.error("Error summarizing article id=%d: %s", article["id"], exc)
    return done


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

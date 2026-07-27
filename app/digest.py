"""The "what you missed" briefing.

The reading list already tells you *what* is unread. A digest is only worth an
LLM call if it tells you which of it matters and how the pieces relate — so it
groups into themes rather than listing headlines back.

Per-user, because "unread" is per-user. Cached against a fingerprint of the
unread set so it is regenerated when that set changes and not before; without
that, every page load would cost a call.
"""

import hashlib
import logging
import re
from html import escape

from sqlalchemy import and_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import articles as A
from app.models import digests as D
from app.models import user_article_state as S
from app.user_topics import NOT_HIDDEN_SQL

log = logging.getLogger(__name__)

MAX_ARTICLES = 40
MIN_ARTICLES = 2

# Observed live: llama3.1:8b writes "[id: 26701]" when a theme cites one
# article, and "[ids: 1, 2]" when it cites several. Matching only the plural
# left the marker rendering as raw debris and linked nothing.
# CJK, Cyrillic, Arabic, Hebrew, Greek, Devanagari. Models drift into another
# script mid-paragraph, and asking nicely in the prompt does not always hold.
_NON_LATIN_RE = re.compile(
    r"[\u0370-\u03ff\u0400-\u04ff\u0590-\u05ff\u0600-\u06ff"
    r"\u0900-\u097f\u3000-\u303f\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]"
)

# A stray character is not worth a second call; a sentence of another script is.
NON_LATIN_TOLERANCE = 3


def has_non_latin(text: str) -> int:
    """How many characters are in a script the briefing should not contain."""
    return len(_NON_LATIN_RE.findall(text or ""))


_IDS_RE = re.compile(r"[\[(]\s*ids?\s*:\s*([0-9,\s#]+?)\s*[\])]", re.IGNORECASE)


def unread_for(db, user_id: int, limit: int = MAX_ARTICLES):
    """Highest-scoring unread articles — what a briefing should cover."""
    stmt = (
        select(A.c.id, A.c.title, A.c.clean_title, A.c.summary, A.c.score, A.c.url)
        .select_from(A.outerjoin(
            S, and_(S.c.article_id == A.c.id, S.c.user_id == user_id)))
        .where(A.c.status == "summarized")
        .where(S.c.read_at.is_(None))
        .where(S.c.dismissed_at.is_(None))
        .where(NOT_HIDDEN_SQL)          # don't brief someone on what they hid
        .order_by(A.c.score.desc().nullslast())
        .limit(limit)
    )
    return db.execute(stmt, {"pref_uid": user_id}).mappings().all()


def fingerprint(rows) -> str:
    ids = sorted(r["id"] for r in rows)
    return hashlib.sha1(",".join(map(str, ids)).encode()).hexdigest()[:16]


def cached(db, user_id: int):
    return db.execute(select(D).where(D.c.user_id == user_id)).mappings().first()


def store(db, user_id: int, body: str, count: int, fp: str) -> None:
    stmt = pg_insert(D).values(user_id=user_id, body=body,
                               article_count=count, fingerprint=fp)
    db.execute(stmt.on_conflict_do_update(
        index_elements=[D.c.user_id],
        set_={"body": body, "article_count": count, "fingerprint": fp,
              "created_at": text("now()")},
    ))


def clear(db, user_id: int) -> None:
    db.execute(D.delete().where(D.c.user_id == user_id))


def linkify(body: str, articles) -> str:
    """Turn the model's `[ids: 1, 2]` markers into links that open the reader.

    `articles` maps id -> url. Ids the model invented are dropped rather than
    rendered as links that go nowhere. The url is carried on the link because a
    cited article may not be in the visible list, so there is no row to read it
    from.
    """
    def _sub(match):
        ids = [int(x) for x in re.findall(r"\d+", match.group(1))]
        good = [i for i in ids if i in articles]
        if not good:
            return ""
        links = ", ".join(
            f'<a href="#" class="digest-link" data-article-id="{i}" '
            f'data-url="{escape(articles[i] or "", quote=True)}">#{i}</a>'
            for i in good
        )
        return f'<span class="digest-refs">{links}</span>'
    return _IDS_RE.sub(_sub, body)


def generate(db, user_id: int, *, model: str, base_url: str, force: bool = False):
    """Return (body, count, from_cache). None body means nothing to report."""
    from app import ollama_client, prompts

    rows = unread_for(db, user_id)
    if len(rows) < MIN_ARTICLES:
        return None, len(rows), False

    fp = fingerprint(rows)
    hit = cached(db, user_id)
    if hit and hit["fingerprint"] == fp and not force:
        return hit["body"], hit["article_count"], True

    items = [{"id": r["id"], "title": r["clean_title"] or r["title"],
              "summary": r["summary"]} for r in rows]
    prompt = prompts.digest_prompt(items)
    body = ollama_client.generate(
        model=model, prompt=prompt, expect_json=False, base_url=base_url,
        action="digest",
    )

    # The briefing is English by design (see prompts.digest_prompt), because it
    # is one piece of prose over a reading list that may mix languages. Asking
    # in the prompt does not always hold, so check, and spend one more call when
    # it did not -- the digest is generated rarely and then cached.
    drift = has_non_latin(body or "")
    if drift > NON_LATIN_TOLERANCE:
        log.warning("Digest for user %d came back with %d non-Latin characters; "
                    "retrying", user_id, drift)
        retry = ollama_client.generate(
            model=model,
            prompt=prompt + "\n\nYour previous attempt used a non-Latin script. "
                            "Write every word in English, Latin alphabet only.",
            expect_json=False, base_url=base_url, action="digest (retry)",
        )
        # Only if it actually improved: never trade a bad briefing for a worse one.
        if retry and retry.strip() and has_non_latin(retry) < drift:
            body = retry

    if not body or not body.strip():
        log.warning("Digest generation returned nothing for user %d", user_id)
        # A stale digest beats none; the caller shows when it was made.
        return (hit["body"], hit["article_count"], True) if hit else (None, len(rows), False)

    body = body.strip()
    store(db, user_id, body, len(rows), fp)
    return body, len(rows), False

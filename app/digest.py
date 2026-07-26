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

from sqlalchemy import and_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import articles as A
from app.models import digests as D
from app.models import user_article_state as S

log = logging.getLogger(__name__)

MAX_ARTICLES = 40
MIN_ARTICLES = 2

_IDS_RE = re.compile(r"\[ids:\s*([0-9,\s]+)\]")


def unread_for(db, user_id: int, limit: int = MAX_ARTICLES):
    """Highest-scoring unread articles — what a briefing should cover."""
    stmt = (
        select(A.c.id, A.c.title, A.c.clean_title, A.c.summary, A.c.score)
        .select_from(A.outerjoin(
            S, and_(S.c.article_id == A.c.id, S.c.user_id == user_id)))
        .where(A.c.status == "summarized")
        .where(S.c.read_at.is_(None))
        .where(S.c.dismissed_at.is_(None))
        .order_by(A.c.score.desc().nullslast())
        .limit(limit)
    )
    return db.execute(stmt).mappings().all()


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


def linkify(body: str, known_ids: set[int]) -> str:
    """Turn the model's `[ids: 1, 2]` markers into links.

    Ids it invented are dropped rather than rendered as dead links.
    """
    def _sub(match):
        ids = [int(x) for x in re.findall(r"\d+", match.group(1))]
        good = [i for i in ids if i in known_ids]
        if not good:
            return ""
        links = ", ".join(
            f'<a href="#" class="digest-link" data-article-id="{i}">#{i}</a>'
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
    body = ollama_client.generate(
        model=model, prompt=prompts.digest_prompt(items),
        expect_json=False, base_url=base_url,
    )
    if not body or not body.strip():
        log.warning("Digest generation returned nothing for user %d", user_id)
        # A stale digest beats none; the caller shows when it was made.
        return (hit["body"], hit["article_count"], True) if hit else (None, len(rows), False)

    body = body.strip()
    store(db, user_id, body, len(rows), fp)
    return body, len(rows), False

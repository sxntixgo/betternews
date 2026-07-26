"""Topic tags and the rules that act on them.

Scores are a soft judgement from a small model. Rules are the hard, auditable
layer on top: an adjustment nudges an article up or down, `muted` hides it
outright regardless of score. That is the difference between "I edited a
paragraph of profile prose and hoped" and "crypto never appears again".
"""

import logging
import re

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import articles as A
from app.models import topic_rules as R

log = logging.getLogger(__name__)

MAX_TOPICS = 4
_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def normalize(raw) -> list[str]:
    """Coerce whatever the model returned into clean slugs."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out, seen = [], set()
    for item in raw:
        slug = _SLUG_RE.sub("-", str(item).strip().lower()).strip("-")
        slug = re.sub(r"-{2,}", "-", slug)[:40]
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out[:MAX_TOPICS]


def vocabulary(db, limit: int = 20) -> list[str]:
    """The most-used existing topics, fed back into the prompt.

    Without this the model invents a new synonym every run and the rules never
    match anything.
    """
    rows = db.execute(
        select(func.unnest(A.c.topics).label("t"), func.count().label("n"))
        .where(A.c.topics.isnot(None))
        .group_by("t").order_by(func.count().desc()).limit(limit)
    ).all()
    return [r[0] for r in rows]


def rules(db) -> dict[str, dict]:
    return {
        r["topic"]: {"adjustment": r["adjustment"], "muted": r["muted"]}
        for r in db.execute(select(R)).mappings().all()
    }


def apply_rules(score: float, topics: list[str], rule_map: dict) -> tuple[float, bool, str | None]:
    """Return (adjusted score, muted, reason-prefix).

    Adjustments sum, so an article tagged with two boosted topics gets both.
    """
    muted_by = next((t for t in topics if rule_map.get(t, {}).get("muted")), None)
    if muted_by:
        return score, True, f"Muted topic: {muted_by}"
    delta = sum(rule_map.get(t, {}).get("adjustment", 0.0) for t in topics)
    if not delta:
        return score, False, None
    adjusted = max(0.0, min(1.0, score + delta))
    return adjusted, False, f"Topic adjustment {delta:+.2f}"


def set_rule(db, topic: str, adjustment: float = 0.0, muted: bool = False) -> None:
    slug = normalize([topic])
    if not slug:
        raise ValueError("Topic is required.")
    if not -1.0 <= adjustment <= 1.0:
        raise ValueError("Adjustment must be between -1.0 and 1.0.")
    stmt = pg_insert(R).values(topic=slug[0], adjustment=adjustment, muted=muted)
    db.execute(stmt.on_conflict_do_update(
        index_elements=[R.c.topic],
        set_={"adjustment": adjustment, "muted": muted},
    ))


def delete_rule(db, topic: str) -> None:
    db.execute(R.delete().where(R.c.topic == topic))


def counts(db, limit: int = 40):
    """Topics by frequency, joined to any rule, for the settings panel."""
    sub = (
        select(func.unnest(A.c.topics).label("topic"), func.count().label("n"))
        .where(A.c.topics.isnot(None))
        .group_by("topic").subquery()
    )
    return db.execute(
        select(sub.c.topic, sub.c.n,
               func.coalesce(R.c.adjustment, 0.0).label("adjustment"),
               func.coalesce(R.c.muted, False).label("muted"))
        .select_from(sub.outerjoin(R, R.c.topic == sub.c.topic))
        .order_by(sub.c.n.desc()).limit(limit)
    ).mappings().all()

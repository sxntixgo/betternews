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

# A cold vocabulary is why early runs produced "ai-tech", "tech-economy" and
# "tecnologia-software-desarrollo": with nothing to anchor to, the model invents
# freely and then the next run anchors to *that*. Seeding gives it a target from
# the first article, and rules stay matchable.
SEED_VOCABULARY = (
    "ai", "software", "hardware", "security", "science", "space", "health",
    "climate", "energy", "business", "economy", "markets", "crypto",
    "politics", "world", "argentina", "us-politics", "europe", "war",
    "sports", "formula-1", "football", "culture", "media", "gaming",
    "transport", "education", "law", "labour", "housing",
)

# Cheap canonicalisation for what the model actually returns. Language drift is
# the common case: "economia" and "economy" must not be separate topics, or a
# mute rule silences one and not the other.
ALIASES = {
    "tecnologia": "software", "tech": "software", "technology": "software",
    "ai-tech": "ai", "artificial-intelligence": "ai", "ia": "ai",
    "economia": "economy", "tech-economy": "economy", "economics": "economy",
    "finance": "markets", "negocios": "business", "empresas": "business",
    "finanzas": "markets", "mercados": "markets",
    "politica": "politics", "politica-economia": "politics",
    "politics-economy": "politics", "geopolitica": "world", "geopolitics": "world",
    "internacional": "world", "mundo": "world", "noticias": None,
    "news": None, "general": None, "other": None, "misc": None,
    "deportes": "sports", "futbol": "football", "f1": "formula-1",
    "salud": "health", "ciencia": "science", "seguridad": "security",
    "educacion": "education", "vivienda": "housing", "transporte": "transport",
    "guerra": "war", "cultura": "culture", "juegos": "gaming",
    "criptomonedas": "crypto", "energia": "energy", "clima": "climate",
}
# Live runs produced "tecnologia-software-desarrollo" and "tech-economy": the
# model compounds concepts when left alone, and a slug nobody will ever type is
# a slug no mute/boost rule will ever match.
MAX_SLUG_WORDS = 2
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
        if slug in ALIASES:
            slug = ALIASES[slug]
            if slug is None:          # contentless labels like "news"
                continue
        elif slug.count("-") + 1 > MAX_SLUG_WORDS:
            log.debug("Dropping compound topic slug %r", slug)
            continue
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out[:MAX_TOPICS]


def vocabulary(db, limit: int = 30) -> list[str]:
    """Topics to offer the model, most-used first, backed by the seed list.

    Merged rather than either/or: the seeds stop a cold start from inventing a
    private taxonomy, and observed topics let a real one grow.
    """
    rows = db.execute(
        select(func.unnest(A.c.topics).label("t"), func.count().label("n"))
        .where(A.c.topics.isnot(None))
        .group_by("t").order_by(func.count().desc()).limit(limit)
    ).all()
    observed = [r[0] for r in rows]
    out = list(observed)
    for seed in SEED_VOCABULARY:
        if seed not in out:
            out.append(seed)
    return out[:limit]


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


def renormalize_all(db) -> int:
    """Re-apply normalisation and aliases to topics already stored.

    Needed whenever ALIASES changes: articles tagged before an alias existed
    keep the old slug, so a mute rule on the canonical name silently misses
    them and /insights splits one topic into two.
    """
    rows = db.execute(
        select(A.c.id, A.c.topics).where(A.c.topics.isnot(None))
    ).mappings().all()
    changed = 0
    for row in rows:
        fixed = normalize(list(row["topics"]))
        if fixed != list(row["topics"]):
            db.execute(
                A.update().where(A.c.id == row["id"])
                .values(topics=fixed or None)
            )
            changed += 1
    log.info("Re-normalised topics on %d articles", changed)
    return changed


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

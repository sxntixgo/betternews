"""Per-user topic stances.

The reader has one shared relevance score per article, because scoring is an
LLM pass and running it per person would multiply the cost by the number of
users. So these preferences deliberately do *not* re-score anything. They are
applied when a list is read:

* ``more`` lifts matching articles within that user's ordering
* ``hide`` removes them from that user's list only

Nobody else's list changes, and the underlying score is untouched — turning a
stance off restores the article exactly.

This is the explicit counterpart to the implicit signal in votes. Votes say what
you actually read; these say what you *think* you want, which is useful when the
two disagree and when there is not yet enough voting history to learn from.
"""

import logging

from sqlalchemy import and_, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import articles as A
from app.models import user_topic_prefs as P
from app.models import votes as V

log = logging.getLogger(__name__)

STANCES = ("more", "hide")

# How much a "more" stance lifts an article inside one user's ordering. Enough
# to reorder within a page, not enough to drag a genuinely poor article to the
# top — the shared score still carries most of the signal.
BOOST = 0.15

_HIDDEN_TOPICS = """(
    SELECT COALESCE(array_agg(topic), '{}') FROM user_topic_prefs
    WHERE user_id = :pref_uid AND stance = 'hide')"""

_BOOSTED_TOPICS = """(
    SELECT COALESCE(array_agg(topic), '{}') FROM user_topic_prefs
    WHERE user_id = :pref_uid AND stance = 'more')"""

# COALESCE so an untagged article is never caught by an overlap test.
NOT_HIDDEN_SQL = text(f"NOT (COALESCE(articles.topics, '{{}}') && {_HIDDEN_TOPICS})")
BOOST_SQL = text(
    f"(CASE WHEN COALESCE(articles.topics, '{{}}') && {_BOOSTED_TOPICS} "
    f"THEN {BOOST} ELSE 0 END)"
)


def stances(db, user_id: int) -> dict[str, str]:
    return {r["topic"]: r["stance"] for r in db.execute(
        select(P.c.topic, P.c.stance).where(P.c.user_id == user_id)
    ).mappings().all()}


def set_stance(db, user_id: int, topic: str, stance: str | None) -> None:
    """Set or clear a stance. `None` means neutral, i.e. remove the row."""
    from app.topics import normalize
    slug = normalize([topic])
    if not slug:
        raise ValueError("Topic is required.")
    if stance is None:
        db.execute(P.delete().where(
            and_(P.c.user_id == user_id, P.c.topic == slug[0])))
        return
    if stance not in STANCES:
        raise ValueError(f"Stance must be one of {', '.join(STANCES)}.")
    stmt = pg_insert(P).values(user_id=user_id, topic=slug[0], stance=stance)
    db.execute(stmt.on_conflict_do_update(
        index_elements=[P.c.user_id, P.c.topic], set_={"stance": stance}))


def clear_all(db, user_id: int) -> int:
    return db.execute(P.delete().where(P.c.user_id == user_id)).rowcount


def for_profile(db, user_id: int, limit: int = 40) -> list[dict]:
    """Topics to offer, ordered by how much this user has engaged with them.

    Their own votes come first: a topic you have actually liked or disliked is
    one you have an opinion about, so it belongs at the top of the list rather
    than whatever happens to be most numerous in the feed.
    """
    rows = db.execute(text("""
        WITH mine AS (
            SELECT t.topic,
                   COUNT(*) FILTER (WHERE v.value = 1)  AS likes,
                   COUNT(*) FILTER (WHERE v.value = -1) AS dislikes
            FROM votes v
            JOIN articles a ON a.id = v.article_id
            CROSS JOIN LATERAL unnest(a.topics) AS t(topic)
            WHERE v.user_id = :uid
            GROUP BY t.topic
        ),
        seen AS (
            SELECT t.topic, COUNT(*) AS articles
            FROM articles a
            CROSS JOIN LATERAL unnest(a.topics) AS t(topic)
            GROUP BY t.topic
        )
        SELECT seen.topic,
               seen.articles,
               COALESCE(mine.likes, 0)    AS likes,
               COALESCE(mine.dislikes, 0) AS dislikes,
               p.stance
        FROM seen
        LEFT JOIN mine ON mine.topic = seen.topic
        LEFT JOIN user_topic_prefs p
               ON p.topic = seen.topic AND p.user_id = :uid
        ORDER BY (COALESCE(mine.likes, 0) + COALESCE(mine.dislikes, 0)) DESC,
                 seen.articles DESC
        LIMIT :n
    """), {"uid": user_id, "n": limit}).mappings().all()
    out = []
    for r in rows:
        voted = r["likes"] + r["dislikes"]
        out.append({
            **dict(r),
            "voted": voted,
            # Only meaningful once there is something to divide by.
            "like_rate": round(100 * r["likes"] / voted) if voted else None,
        })
    return out


def suggestions(db, user_id: int, min_votes: int = 3) -> dict[str, list[str]]:
    """Topics this user's own voting already argues for or against.

    Surfacing these is the "training" part: the stance is explicit, but the
    evidence for it comes from what they actually did.
    """
    rows = for_profile(db, user_id, limit=100)
    likes = [r["topic"] for r in rows
             if r["voted"] >= min_votes and r["like_rate"] is not None
             and r["like_rate"] >= 70 and r["stance"] != "more"]
    dislikes = [r["topic"] for r in rows
                if r["voted"] >= min_votes and r["like_rate"] is not None
                and r["like_rate"] <= 20 and r["stance"] != "hide"]
    return {"more": likes[:5], "hide": dislikes[:5]}

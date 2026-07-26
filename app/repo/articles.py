"""Article reads and per-user state changes.

Every function here takes ``user_id``. `articles` rows are shared; what a person
has read, saved, dismissed or voted on is not, and conflating the two is how one
user's dismiss removes an article from everyone's list.
"""

from sqlalchemy import Integer, and_, case, func, literal, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import articles as A
from app.models import feeds as F
from app.models import user_article_state as S
from app.models import votes as V

# Pipeline lifecycle values that are eligible to appear in the reading list.
VISIBLE_STATUSES = ("summarized",)
HIDDEN_STATUSES = ("hidden",)

_FULL_TEXT_HEAD = func.substr(A.c.full_text, 1, 400).label("full_text_head")


def _card_select(user_id: int):
    """Columns the article card template needs, joined to this user's state."""
    return (
        select(
            A.c.id, A.c.url, A.c.title, A.c.summary, A.c.score, A.c.score_reason,
            A.c.status, A.c.thumbnail_url, A.c.raw_snippet, A.c.clean_title,
            A.c.title_was_clickbait, A.c.feed_id, A.c.topics, A.c.cluster_id,
            S.c.read_at, S.c.saved_at, S.c.opinion,
            _FULL_TEXT_HEAD,
        )
        .select_from(
            A.outerjoin(S, and_(S.c.article_id == A.c.id, S.c.user_id == user_id))
        )
    )


def _visible(stmt):
    """Exclude what this user dismissed — without touching anyone else's list."""
    return stmt.where(S.c.dismissed_at.is_(None))


def list_for_user(db, user_id: int, *, hidden: bool = False, saved: bool = False,
                  feed_id: int | None = None, sort: str = "date",
                  topic: str | None = None, limit: int = 50, offset: int = 0):
    stmt = _visible(_card_select(user_id))
    stmt = stmt.where(A.c.status.in_(HIDDEN_STATUSES if hidden else VISIBLE_STATUSES))
    if topic:
        stmt = stmt.where(A.c.topics.any(topic))
    if saved:
        stmt = stmt.where(S.c.saved_at.isnot(None))
    if feed_id is not None:
        stmt = stmt.where(A.c.feed_id == feed_id)
    order = ([A.c.published_at.desc().nullslast()] if sort == "date"
             else [A.c.score.desc().nullslast(), A.c.published_at.desc().nullslast()])
    rows = db.execute(
        stmt.order_by(*order).limit(limit * 3).offset(offset)
    ).mappings().all()
    return _collapse_clusters(db, rows, limit)


def _collapse_clusters(db, rows, limit: int):
    """Keep the best-scoring member of each cluster, noting the others.

    Over-fetches so collapsing does not leave a short page.
    """
    seen: dict[str, dict] = {}
    out: list[dict] = []
    for row in rows:
        key = row["cluster_id"]
        if not key:
            out.append(dict(row))
            continue
        if key in seen:
            seen[key]["duplicate_count"] = seen[key].get("duplicate_count", 0) + 1
            continue
        d = dict(row)
        d["duplicate_count"] = 0
        seen[key] = d
        out.append(d)
        if len(out) >= limit:
            break
    return out[:limit]


def get_card(db, user_id: int, article_id: int):
    stmt = _card_select(user_id).where(A.c.id == article_id)
    return db.execute(stmt).mappings().first()


def search(db, user_id: int, query: str, limit: int = 50):
    """Full-text search via the generated tsvector column.

    ``websearch_to_tsquery`` accepts quoted phrases and -exclusions and, unlike
    FTS5 ``MATCH``, does not raise on malformed input.
    """
    tsq = func.websearch_to_tsquery("english", query)
    stmt = (
        _visible(_card_select(user_id))
        .where(A.c.search_vector.op("@@")(tsq))
        .where(A.c.status.in_(VISIBLE_STATUSES + HIDDEN_STATUSES))
        .order_by(func.ts_rank(A.c.search_vector, tsq).desc())
        .limit(limit)
    )
    return db.execute(stmt).mappings().all()


def _upsert_state(db, user_id: int, article_id: int, **values):
    stmt = pg_insert(S).values(user_id=user_id, article_id=article_id, **values)
    db.execute(stmt.on_conflict_do_update(
        index_elements=[S.c.user_id, S.c.article_id], set_=values
    ))


def exists(db, article_id: int) -> bool:
    return db.execute(
        select(literal(1)).where(A.c.id == article_id)
    ).first() is not None


def mark_read(db, user_id: int, article_id: int) -> None:
    """First open only — a re-read must not move the timestamp."""
    stmt = pg_insert(S).values(user_id=user_id, article_id=article_id,
                               read_at=func.now())
    db.execute(stmt.on_conflict_do_update(
        index_elements=[S.c.user_id, S.c.article_id],
        set_={"read_at": func.coalesce(S.c.read_at, func.now())},
    ))


def toggle_saved(db, user_id: int, article_id: int) -> None:
    row = db.execute(
        select(S.c.saved_at).where(
            and_(S.c.user_id == user_id, S.c.article_id == article_id))
    ).first()
    _upsert_state(db, user_id, article_id,
                  saved_at=None if (row and row[0]) else func.now())


def dismiss(db, user_id: int, article_id: int) -> None:
    _upsert_state(db, user_id, article_id, dismissed_at=func.now())


def dismiss_all(db, user_id: int, feed_id: int | None = None) -> int:
    """Dismiss everything currently listed for this user."""
    stmt = select(A.c.id).where(A.c.status.in_(VISIBLE_STATUSES))
    if feed_id is not None:
        stmt = stmt.where(A.c.feed_id == feed_id)
    ids = [r[0] for r in db.execute(stmt).all()]
    for aid in ids:
        _upsert_state(db, user_id, aid, dismissed_at=func.now())
    return len(ids)


def record_vote(db, user_id: int, article_id: int, value: int) -> None:
    """Store the opinion for display *and* an immutable training record.

    The snapshot is what lets retention delete the article later without the
    preference profile losing the vote — see docs/feature-plan.md 0.9d.
    """
    row = db.execute(
        select(A.c.title, A.c.summary).where(A.c.id == article_id)
    ).first()
    db.execute(V.insert().values(
        user_id=user_id, article_id=article_id, value=value,
        title_snapshot=row[0] if row else None,
        summary_snapshot=row[1] if row else None,
    ))
    _upsert_state(db, user_id, article_id,
                  opinion="liked" if value == 1 else "disliked")


def unread_count(db, user_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(A.outerjoin(
            S, and_(S.c.article_id == A.c.id, S.c.user_id == user_id)))
        .where(A.c.status.in_(VISIBLE_STATUSES))
        .where(S.c.read_at.is_(None))
        .where(S.c.dismissed_at.is_(None))
    )
    return db.execute(stmt).scalar_one()


def sidebar_counts(db, user_id: int):
    """Per-feed unread / hidden / saved tallies for the sidebar."""
    joined = F.outerjoin(A, A.c.feed_id == F.c.id).outerjoin(
        S, and_(S.c.article_id == A.c.id, S.c.user_id == user_id))
    stmt = (
        select(
            F.c.id,
            func.coalesce(F.c.title, F.c.url).label("title"),
            F.c.paused, F.c.tags,
            func.sum(case(
                (and_(A.c.status == "summarized", S.c.read_at.is_(None),
                      S.c.dismissed_at.is_(None)), 1), else_=0
            ).cast(Integer)).label("unread"),
            func.sum(case((A.c.status == "hidden", 1), else_=0).cast(Integer)).label("hidden"),
            func.sum(case((S.c.saved_at.isnot(None), 1), else_=0).cast(Integer)).label("saved"),
        )
        .select_from(joined)
        .group_by(F.c.id)
        .order_by(func.coalesce(F.c.title, F.c.url))
    )
    return db.execute(stmt).mappings().all()


def rescore_hidden(db) -> int:
    """Push hidden articles back through scoring. Not user-scoped: scores are
    global, so this affects the shared ranking."""
    res = db.execute(
        A.update().where(A.c.status == "hidden").values(status="new")
    )
    return res.rowcount


def status_counts(db):
    return db.execute(
        select(A.c.status, func.count().label("n")).group_by(A.c.status)
    ).mappings().all()

"""Article reads and per-user state changes.

Every function here takes ``user_id``. `articles` rows are shared; what a person
has read, saved, dismissed or voted on is not, and conflating the two is how one
user's dismiss removes an article from everyone's list.
"""

from sqlalchemy import (Integer, Text, and_, case, cast, func, literal,
                        select, text)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import articles as A
from app.models import feeds as F
from app.models import user_article_state as S
from app.models import votes as V
from app.user_topics import BOOST_SQL, NOT_HIDDEN_SQL

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
            S.c.read_at, S.c.saved_at, S.c.opinion, S.c.dismissed_at,
            _FULL_TEXT_HEAD,
        )
        .select_from(
            A.outerjoin(S, and_(S.c.article_id == A.c.id, S.c.user_id == user_id))
        )
    )


def _visible(stmt, dismissed: bool):
    """Split the list in two: what you have not dealt with, and what you have.

    Dismissed articles used to stay inline, greyed out. That was a correction of
    an earlier mistake -- filtering them out entirely made a dismissal
    indistinguishable from an article that never arrived, with nothing to review
    and no way back -- but it overshot. On a corpus this size the greyed-out
    rows are most of what you scroll past, and `dismiss-all` is one button, so a
    single press could bury the unread list under thousands of them.

    So they are still reachable, just not in the way: the reader asks for them
    and they page in like anything else. Nothing is deleted here either way;
    only retention removes an article.

    Kept as a function rather than inlined: this is where the decision lives,
    and the unread counts deliberately do NOT use it -- a dismissed article is
    visible but not unread.
    """
    return stmt.where(S.c.dismissed_at.isnot(None) if dismissed
                      else S.c.dismissed_at.is_(None))


class Page(list):
    """Rows for one page, plus where the next page actually starts.

    A list subclass rather than a tuple because the offset is only interesting
    to the one route that paginates; every other caller wants the rows and
    nothing else, and keeps working unchanged.

    `next_offset` is None at the end of the list. It is simply
    ``offset + limit`` now that collapsing happens in SQL -- the offset counts
    articles the reader sees, so there is nothing to correct for.
    """
    next_offset: int | None = None


def list_for_user(db, user_id: int, *, hidden: bool = False, saved: bool = False,
                  feed_id: int | None = None, sort: str = "date",
                  topic: str | None = None, limit: int = 50, offset: int = 0,
                  dismissed: bool = False):
    stmt = _visible(_card_select(user_id), dismissed)
    stmt = stmt.where(A.c.status.in_(HIDDEN_STATUSES if hidden else VISIBLE_STATUSES))
    if topic:
        # An explicit topic filter is a deliberate request, so it overrides the
        # user's own hide stance for that topic.
        stmt = stmt.where(A.c.topics.any(topic))
    else:
        stmt = stmt.where(NOT_HIDDEN_SQL)
    if saved:
        # Something you saved is something you asked to keep.
        stmt = stmt.where(S.c.saved_at.isnot(None))
    if feed_id is not None:
        stmt = stmt.where(A.c.feed_id == feed_id)

    # The boost reorders within this user's list; the stored score is untouched.
    effective = (func.coalesce(A.c.score, 0) + BOOST_SQL).label("effective_score")

    # An un-clustered article is a cluster of one. Without the COALESCE every
    # row with cluster_id IS NULL shares a single key and the whole list
    # collapses to one article -- the first thing to get wrong here, and the
    # loudest.
    cluster_expr = func.coalesce(A.c.cluster_id, cast(A.c.id, Text))

    # Window functions are evaluated before DISTINCT ON, so this counts every
    # copy in the cluster, not the one that survives.
    duplicates = (func.count().over(partition_by=cluster_expr) - 1).label(
        "duplicate_count")

    # published_at is not in _card_select, but the outer query has to sort by it.
    inner = stmt.add_columns(A.c.published_at, effective,
                             cluster_expr.label("cluster_key"), duplicates)

    # DISTINCT ON keeps the first row per cluster in *this* order, which is what
    # the old Python loop did: it kept whichever copy the display order reached
    # first, not the highest-scoring one, whatever its docstring claimed.
    # id last, always. published_at ties are common -- a feed stamps a whole
    # batch with one timestamp -- and without a unique tiebreaker the sort is
    # unstable, so LIMIT/OFFSET can hand the same article to two pages and skip
    # another entirely. That is the bug this phase exists to remove, and it does
    # not care whether collapsing happens in Python or SQL.
    within = ([A.c.published_at.desc().nullslast(), A.c.id.desc()] if sort == "date"
              else [effective.desc(), A.c.published_at.desc().nullslast(),
                    A.c.id.desc()])
    collapsed = (inner.distinct(cluster_expr)
                 .order_by(cluster_expr, *within)
                 .subquery("collapsed"))

    # Collapsing now happens before LIMIT/OFFSET, so the offset counts articles
    # the reader actually sees. That is the whole point: paging is exact, and a
    # cluster split across a page boundary can no longer appear twice.
    outer = ([collapsed.c.published_at.desc().nullslast(), collapsed.c.id.desc()]
             if sort == "date"
             else [collapsed.c.effective_score.desc(),
                   collapsed.c.published_at.desc().nullslast(),
                   collapsed.c.id.desc()])
    rows = db.execute(
        select(collapsed).order_by(*outer).limit(limit).offset(offset),
        {"pref_uid": user_id},
    ).mappings().all()

    page = Page(dict(r) for r in rows)
    page.next_offset = offset + limit if len(page) == limit else None
    return page


def get_card(db, user_id: int, article_id: int):
    stmt = _card_select(user_id).where(A.c.id == article_id)
    return db.execute(stmt).mappings().first()


def search(db, user_id: int, query: str, limit: int = 50):
    """Full-text search via the generated tsvector column.

    ``websearch_to_tsquery`` accepts quoted phrases and -exclusions and, unlike
    FTS5 ``MATCH``, does not raise on malformed input.
    """
    tsq = func.websearch_to_tsquery("english", query)
    # Deliberately not split by `_visible`: search is someone looking for a
    # specific article they remember, and whether they dismissed it afterwards
    # is not part of the question. Hiding it here would look like the article
    # was deleted.
    stmt = (
        _card_select(user_id)
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


def dismiss_all(db, user_id: int, feed_id: int | None = None, *,
                hidden: bool = False, saved: bool = False,
                topic: str | None = None) -> int:
    """Dismiss everything currently listed for this user.

    "Currently listed" has to mean the list actually on screen. This only ever
    matched VISIBLE_STATUSES, so pressing Dismiss all while viewing Hidden
    dismissed the *main* list instead: the hidden articles stayed, their count
    did not move, and the articles that did get dismissed were somewhere the
    reader could not see. The filters here mirror `list_for_user`.
    """
    stmt = select(A.c.id).where(
        A.c.status.in_(HIDDEN_STATUSES if hidden else VISIBLE_STATUSES))
    if feed_id is not None:
        stmt = stmt.where(A.c.feed_id == feed_id)
    if topic:
        stmt = stmt.where(A.c.topics.any(topic))
    if saved:
        stmt = stmt.where(select(literal(1)).where(and_(
            S.c.article_id == A.c.id, S.c.user_id == user_id,
            S.c.saved_at.isnot(None))).exists())
    # One statement, not one per article. Dismissing 6,128 hidden articles was
    # 6,128 round trips and took long enough that the sidebar refreshed before
    # the write finished, so the count appeared not to have changed at all.
    ins = pg_insert(S).from_select(
        ["user_id", "article_id", "dismissed_at"],
        select(literal(user_id), A.c.id, func.now()).select_from(A)
        .where(A.c.id.in_(stmt)),
    )
    # RETURNING rather than rowcount: psycopg reports -1 for INSERT ... FROM
    # SELECT, and the caller shows this number to the reader.
    result = db.execute(ins.on_conflict_do_update(
        index_elements=[S.c.user_id, S.c.article_id],
        set_={"dismissed_at": func.now()},
    ).returning(S.c.article_id))
    return len(result.fetchall())


def record_vote(db, user_id: int, article_id: int, value: int) -> None:
    """Store the opinion for display *and* an immutable training record.

    The snapshot is what lets retention delete the article later without the
    preference profile losing the vote — see docs/feature-plan.md 0.9d.
    """
    row = db.execute(
        select(A.c.title, A.c.summary, A.c.topics, A.c.kind).where(A.c.id == article_id)
    ).first()
    db.execute(V.insert().values(
        user_id=user_id, article_id=article_id, value=value,
        title_snapshot=row[0] if row else None,
        summary_snapshot=row[1] if row else None,
        # Topic affinity is computed from these. Reading them back off the
        # article later would mean the reader's learned preferences decayed
        # every time retention ran.
        topics_snapshot=row[2] if row else None,
        kind_snapshot=row[3] if row else None,
    ))
    _upsert_state(db, user_id, article_id,
                  opinion="liked" if value == 1 else "disliked")


def high_score_unnotified(db, user_id: int, threshold: float, limit: int = 5):
    """Articles worth interrupting someone for, that they haven't been told about.

    `notified_at` lives in user_article_state, so each person is notified once —
    a shared flag on the article would silence everyone after the first.
    """
    stmt = (
        select(A.c.id, A.c.title, A.c.clean_title, A.c.score)
        .select_from(A.outerjoin(
            S, and_(S.c.article_id == A.c.id, S.c.user_id == user_id)))
        .where(A.c.status == "summarized")
        .where(A.c.score >= threshold)
        .where(S.c.read_at.is_(None))
        .where(S.c.dismissed_at.is_(None))
        .where(S.c.notified_at.is_(None))
        .order_by(A.c.score.desc())
        .limit(limit)
    )
    return db.execute(stmt).mappings().all()


def mark_notified(db, user_id: int, article_ids: list[int]) -> None:
    for aid in article_ids:
        _upsert_state(db, user_id, aid, notified_at=func.now())


def unread_count(db, user_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(A.outerjoin(
            S, and_(S.c.article_id == A.c.id, S.c.user_id == user_id)))
        .where(A.c.status.in_(VISIBLE_STATUSES))
        .where(S.c.read_at.is_(None))
        .where(S.c.dismissed_at.is_(None))
        .where(NOT_HIDDEN_SQL)
    )
    return db.execute(stmt, {"pref_uid": user_id}).scalar_one()


def unread_since(db, user_id: int, since) -> int:
    """`unread_count`, restricted to articles ingested since `since`.

    Keyed on `created_at` (ingest time), never `published_at` -- feeds carry
    wrong and future publication dates, which is why retention keys on
    `created_at` too.
    """
    stmt = (
        select(func.count())
        .select_from(A.outerjoin(
            S, and_(S.c.article_id == A.c.id, S.c.user_id == user_id)))
        .where(A.c.status.in_(VISIBLE_STATUSES))
        .where(S.c.read_at.is_(None))
        .where(S.c.dismissed_at.is_(None))
        .where(NOT_HIDDEN_SQL)
        .where(A.c.created_at >= since)
    )
    return db.execute(stmt, {"pref_uid": user_id}).scalar_one()


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
            # Dismissed articles drop out of this tally for the same reason they
            # drop out of `unread`: the badge counts what still wants attention,
            # while the list below shows everything, greyed. Without the
            # condition the Hidden count never moved, whatever you dismissed.
            func.sum(case(
                (and_(A.c.status == "hidden", S.c.dismissed_at.is_(None)), 1), else_=0
            ).cast(Integer)).label("hidden"),
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

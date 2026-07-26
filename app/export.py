"""Markdown export.

A reading tool should let its data leave. One file per article with YAML front
matter, which is what Obsidian and most note tools expect.
"""

import io
import re
import zipfile
from datetime import datetime, timezone

from sqlalchemy import and_, select

from app.models import articles as A
from app.models import feeds as F
from app.models import user_article_state as S

SCOPES = ("saved", "liked", "all")


def _rows(db, user_id: int, scope: str):
    stmt = (
        select(A.c.id, A.c.title, A.c.clean_title, A.c.url, A.c.summary,
               A.c.full_text, A.c.published_at, A.c.score, A.c.topics,
               F.c.title.label("feed_title"), F.c.url.label("feed_url"),
               S.c.saved_at, S.c.read_at, S.c.opinion)
        .select_from(
            A.join(F, F.c.id == A.c.feed_id)
             .outerjoin(S, and_(S.c.article_id == A.c.id, S.c.user_id == user_id))
        )
        .where(S.c.dismissed_at.is_(None))
    )
    if scope == "saved":
        stmt = stmt.where(S.c.saved_at.isnot(None))
    elif scope == "liked":
        stmt = stmt.where(S.c.opinion == "liked")
    else:
        stmt = stmt.where(A.c.status == "summarized")
    return db.execute(stmt.order_by(A.c.published_at.desc().nullslast())).mappings().all()


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (text or "").lower()).strip()
    s = re.sub(r"[\s_]+", "-", s)[:60].strip("-")
    return s or fallback


def _yaml(value) -> str:
    """Quote defensively — a colon or a quote in a title breaks the front matter."""
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_markdown(row) -> str:
    title = row["clean_title"] or row["title"]
    front = [
        "---",
        f"title: {_yaml(title)}",
    ]
    if row["clean_title"] and row["clean_title"] != row["title"]:
        front.append(f"original_title: {_yaml(row['title'])}")
    front += [
        f"url: {_yaml(row['url'])}",
        f"feed: {_yaml(row['feed_title'] or row['feed_url'])}",
        f"published: {_yaml(row['published_at'])}",
        f"score: {_yaml(row['score'])}",
        f"topics: [{', '.join(_yaml(t) for t in (row['topics'] or []))}]",
        f"saved: {_yaml(bool(row['saved_at']))}",
        f"opinion: {_yaml(row['opinion'])}",
        f"exported: {_yaml(datetime.now(timezone.utc))}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    if row["summary"]:
        front += ["> " + row["summary"].replace("\n", " "), ""]
    body = (row["full_text"] or "").strip()
    front += [body if body else "_No full text was extracted for this article._", ""]
    front += [f"[Read the original]({row['url']})", ""]
    return "\n".join(front)


def build_zip(db, user_id: int, scope: str) -> tuple[bytes, int]:
    rows = _rows(db, user_id, scope)
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            name = _slug(row["clean_title"] or row["title"], f"article-{row['id']}")
            # Two articles can share a headline; the id keeps names unique.
            fname = f"{name}-{row['id']}.md"
            if fname in used:                       # pragma: no cover - ids are unique
                fname = f"{name}-{row['id']}-dup.md"
            used.add(fname)
            zf.writestr(fname, to_markdown(row))
        if not rows:
            zf.writestr("README.md",
                        "# Nothing to export\n\nNo articles matched this scope.\n")
    return buf.getvalue(), len(rows)

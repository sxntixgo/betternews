"""Folders: groups of feeds the reader makes by hand.

Shared, like feeds: one list of folders for everyone, changed by an admin.
Names are unique ignoring case (a unique index on lower(name)).
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import feeds as F
from app.models import folders as D


class DuplicateName(Exception):
    pass


def _with_counts():
    n = select(func.count()).select_from(F).where(F.c.folder_id == D.c.id).scalar_subquery()
    return select(D.c.id, D.c.name, n.label("feeds"))


def all_(db):
    """Every folder with how many feeds are in it, alphabetically."""
    return db.execute(_with_counts().order_by(func.lower(D.c.name))).mappings().all()


def get(db, folder_id: int):
    return db.execute(_with_counts().where(D.c.id == folder_id)).mappings().first()


def create(db, name: str) -> int:
    try:
        with db.begin_nested():
            return db.execute(D.insert().values(name=name).returning(D.c.id)).scalar_one()
    except IntegrityError as exc:
        raise DuplicateName(name) from exc


def rename(db, folder_id: int, name: str) -> None:
    try:
        with db.begin_nested():
            db.execute(D.update().where(D.c.id == folder_id).values(name=name))
    except IntegrityError as exc:
        raise DuplicateName(name) from exc


def delete(db, folder_id: int) -> None:
    # The foreign key's ON DELETE SET NULL unfiles the feeds.
    db.execute(D.delete().where(D.c.id == folder_id))

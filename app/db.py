"""Database plumbing: engine, request-scoped connections, settings helpers.

No business logic — that lives in `app/repo/`.

The engine is created lazily on first use rather than at import, so tests can
point `DATABASE_URL` at a throwaway database before anything connects.
"""

import os

import flask
from sqlalchemy import create_engine, delete, insert, select, text, update
from sqlalchemy.engine import Connection, Engine

from app.models import metadata, settings as settings_t

DEFAULT_URL = "postgresql+psycopg://betterread:betterread@db:5432/betterread"

_engine: Engine | None = None


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            database_url(),
            pool_pre_ping=True,   # a Postgres restart shouldn't poison the pool
            pool_size=5,
            max_overflow=5,
            future=True,
        )
    return _engine


def dispose_engine() -> None:
    """Drop the pooled engine. Used by tests between databases."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def get_db() -> Connection:
    """Request-scoped connection. Committed by `close_db` on a clean response."""
    if "db" not in flask.g:
        flask.g.db = get_engine().connect()
    return flask.g.db


def get_db_direct() -> Connection:
    """Standalone connection for background jobs. Caller must close it."""
    return get_engine().connect()


def close_db(e: BaseException | None = None) -> None:
    db = flask.g.pop("db", None)
    if db is not None:
        try:
            if e is None:
                db.commit()
            else:
                db.rollback()
        finally:
            db.close()


def init_db() -> None:
    """Create any missing tables.

    Alembic owns migrations; this is the first-run convenience path and the
    fixture used by tests. `create_all` is a no-op against an existing schema.
    """
    metadata.create_all(get_engine())


def get_setting(db: Connection, key: str, default: str = "") -> str:
    row = db.execute(
        select(settings_t.c.value).where(settings_t.c.key == key)
    ).first()
    return row[0] if row else default


def set_setting(db: Connection, key: str, value: str) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(settings_t).values(key=key, value=value)
    db.execute(stmt.on_conflict_do_update(
        index_elements=[settings_t.c.key], set_={"value": stmt.excluded.value}
    ))


__all__ = [
    "database_url", "get_engine", "dispose_engine", "get_db", "get_db_direct",
    "close_db", "init_db", "get_setting", "set_setting",
    "select", "insert", "update", "delete", "text",
]

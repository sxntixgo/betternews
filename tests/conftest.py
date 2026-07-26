"""Shared fixtures.

Postgres has no in-memory mode, so tests run against a real server (the `db`
service, or DATABASE_URL). Each test gets a schema created and dropped around
it, which also means every run exercises the real DDL.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from app.models import metadata

ADMIN_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://betterread:betterread@db:5432/betterread",
)


@pytest.fixture(scope="session")
def _admin_engine():
    eng = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def database_url(_admin_engine):
    """A throwaway database per test, so nothing leaks between them."""
    name = f"t_{uuid.uuid4().hex[:16]}"
    with _admin_engine.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    yield url
    from app.db import dispose_engine
    dispose_engine()
    with _admin_engine.connect() as c:
        c.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :n AND pid <> pg_backend_pid()"), {"n": name})
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))


@pytest.fixture
def app(database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "")

    from app.db import dispose_engine
    dispose_engine()

    from app import create_app
    application = create_app()
    application.config["TESTING"] = True
    yield application
    dispose_engine()


@pytest.fixture
def anon_client(app):
    """Signed-out client, for testing the auth boundary itself."""
    return app.test_client()


@pytest.fixture
def admin_user(app):
    """The account that owns the pre-accounts data (see repo.users)."""
    from app.db import get_db_direct
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        uid = ensure_bootstrap_user(db)
        db.commit()
        db.close()
    return uid


@pytest.fixture
def client(app, admin_user):
    """Signed in as an admin.

    Almost every route is behind a session now, and the suite predates
    accounts, so the default client is authenticated. Use `anon_client` to
    assert the gate, and `login_as` for a non-admin.
    """
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = admin_user
    return c


@pytest.fixture
def login_as(app):
    """Factory: sign a client in as a user with the given role."""
    def _make(username="member", role="user", must_change_password=False):
        from app.db import get_db_direct
        from sqlalchemy import text as _t
        with app.app_context():
            db = get_db_direct()
            uid = add_user(db, username=username, role=role)
            if must_change_password:
                db.execute(_t("UPDATE users SET must_change_password=true WHERE id=:i"),
                           {"i": uid})
                db.commit()
            db.close()
        c = app.test_client()
        with c.session_transaction() as sess:
            sess["user_id"] = uid
        return c, uid
    return _make


@pytest.fixture
def db_conn(app):
    from app.db import get_db_direct
    with app.app_context():
        conn = get_db_direct()
        yield conn
        conn.close()


@pytest.fixture
def memory_db(app):
    """Standalone connection with the schema applied.

    Named for the SQLite in-memory database it replaced; kept so the existing
    pipeline tests read unchanged.
    """
    from app.db import get_db_direct
    with app.app_context():
        conn = get_db_direct()
        yield conn
        conn.rollback()
        conn.close()


def _engine_for(conn):
    return conn


def add_user(db, username: str = "tester", role: str = "admin") -> int:
    from app.models import users
    uid = db.execute(
        users.insert().values(username=username, password_hash="x", role=role)
        .returning(users.c.id)
    ).scalar_one()
    db.commit()
    return uid


def add_feed(db, url: str = "https://example.com/rss", title: str | None = None) -> int:
    from app.models import feeds
    fid = db.execute(
        feeds.insert().values(url=url, title=title).returning(feeds.c.id)
    ).scalar_one()
    db.commit()
    return fid


def add_article(db, feed_id: int, **kwargs) -> int:
    """Insert an article.

    ``read_at``/``saved_at``/``status='liked'`` are per-user now, so those kwargs
    are routed into user_article_state against the bootstrap user rather than
    onto the article row.
    """
    from app.models import articles, user_article_state
    from app.repo.users import ensure_bootstrap_user

    seq = kwargs.pop("seq", 1)
    read_at = kwargs.pop("read_at", None)
    saved_at = kwargs.pop("saved_at", None)
    status = kwargs.pop("status", "summarized")
    opinion = None
    dismissed_at = kwargs.pop("dismissed_at", None)
    if status in ("liked", "disliked"):
        opinion, status = status, "summarized"
    elif status == "dismissed":
        from datetime import datetime, timezone
        dismissed_at, status = datetime.now(timezone.utc), "summarized"

    values = dict(
        feed_id=feed_id,
        guid=kwargs.pop("guid", f"g-{feed_id}-{seq}"),
        url=kwargs.pop("url", "https://example.com/a/1"),
        title=kwargs.pop("title", "Test Title"),
        raw_snippet=kwargs.pop("raw_snippet", "Snippet"),
        feed_content=kwargs.pop("feed_content", None),
        full_text=kwargs.pop("full_text", None),
        summary=kwargs.pop("summary", "A summary."),
        score=kwargs.pop("score", 0.8),
        status=status,
        thumbnail_url=kwargs.pop("thumbnail_url", None),
    )
    values.update(kwargs)
    aid = db.execute(
        articles.insert().values(**values).returning(articles.c.id)
    ).scalar_one()

    if read_at or saved_at or opinion or dismissed_at:
        uid = ensure_bootstrap_user(db)
        db.execute(user_article_state.insert().values(
            user_id=uid, article_id=aid, read_at=read_at, saved_at=saved_at,
            opinion=opinion, dismissed_at=dismissed_at,
        ))
    db.commit()
    return aid

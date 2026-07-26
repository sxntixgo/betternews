from app.db import get_db_direct, get_setting, set_setting


def test_settings_get_default(app):
    with app.app_context():
        db = get_db_direct()
        assert get_setting(db, "missing", "fallback") == "fallback"
        assert get_setting(db, "missing") == ""
        db.close()


def test_settings_set_and_get(app):
    with app.app_context():
        db = get_db_direct()
        set_setting(db, "k", "v1")
        db.commit()
        assert get_setting(db, "k") == "v1"
        # upsert
        set_setting(db, "k", "v2")
        db.commit()
        assert get_setting(db, "k") == "v2"
        db.close()


def test_init_db_idempotent(app):
    """Calling init_db twice (start-up + ALTERs) should not raise."""
    from app.db import init_db
    with app.app_context():
        init_db()
        init_db()


def test_close_db_handles_no_connection(app):
    from app.db import close_db
    with app.app_context():
        close_db()  # no connection on g — should be a no-op




def test_close_db_rolls_back_on_exception(app):
    """A failed request must not commit half its work."""
    from app.db import get_db, close_db
    from sqlalchemy import text
    with app.test_request_context():
        db = get_db()
        db.execute(text("INSERT INTO feeds (url) VALUES ('https://rollback.test/f')"))
        close_db(RuntimeError("request blew up"))

    from app.db import get_db_direct
    with app.app_context():
        conn = get_db_direct()
        n = conn.execute(text(
            "SELECT COUNT(*) FROM feeds WHERE url='https://rollback.test/f'")).scalar()
        conn.close()
    assert n == 0


def test_close_db_commits_on_success(app):
    from app.db import get_db, close_db, get_db_direct
    from sqlalchemy import text
    with app.test_request_context():
        db = get_db()
        db.execute(text("INSERT INTO feeds (url) VALUES ('https://commit.test/f')"))
        close_db(None)
    with app.app_context():
        conn = get_db_direct()
        n = conn.execute(text(
            "SELECT COUNT(*) FROM feeds WHERE url='https://commit.test/f'")).scalar()
        conn.close()
    assert n == 1

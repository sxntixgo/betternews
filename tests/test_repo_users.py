"""Account lookups. Phase 1 builds registration and sessions on these."""

from tests.conftest import add_user


def test_bootstrap_user_is_created_once(db_conn):
    from app.repo.users import ensure_bootstrap_user, count
    first = ensure_bootstrap_user(db_conn)
    db_conn.commit()
    second = ensure_bootstrap_user(db_conn)
    assert first == second
    assert count(db_conn) == 1


def test_bootstrap_adopts_an_existing_account(db_conn):
    """It must not create a parallel owner when accounts already exist."""
    from app.repo.users import ensure_bootstrap_user, count
    uid = add_user(db_conn, username="someone")
    assert ensure_bootstrap_user(db_conn) == uid
    assert count(db_conn) == 1


def test_get_returns_the_row(db_conn):
    from app.repo.users import get
    uid = add_user(db_conn, username="alice")
    assert get(db_conn, uid)["username"] == "alice"


def test_get_unknown_id_is_none(db_conn):
    from app.repo.users import get
    assert get(db_conn, 424242) is None


def test_by_username_is_case_insensitive(db_conn):
    from app.repo.users import by_username
    add_user(db_conn, username="Alice")
    assert by_username(db_conn, "alice")["username"] == "Alice"
    assert by_username(db_conn, "  ALICE  ")["username"] == "Alice"


def test_by_username_unknown_is_none(db_conn):
    from app.repo.users import by_username
    assert by_username(db_conn, "nobody") is None
    assert by_username(db_conn, "") is None


def test_username_uniqueness_ignores_case(db_conn):
    """The lower(username) index is what COLLATE NOCASE used to do."""
    import pytest
    from sqlalchemy.exc import IntegrityError
    add_user(db_conn, username="Bob")
    with pytest.raises(IntegrityError):
        add_user(db_conn, username="bob")

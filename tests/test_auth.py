"""Accounts, sessions, role gating and admin user management."""

import pytest
from sqlalchemy import text

from tests.conftest import add_user


def _count_users(app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        n = db.execute(text("SELECT COUNT(*) FROM users")).scalar()
        db.close()
    return n


def _user(app, username):
    from app.db import get_db_direct
    from app.repo.users import by_username
    with app.app_context():
        db = get_db_direct()
        row = by_username(db, username)
        db.close()
    return row


# ── registration ───────────────────────────────────────────────────────────────

def test_first_account_becomes_admin(anon_client, app):
    r = anon_client.post("/register", data={
        "username": "first", "password": "correct-horse", "confirm": "correct-horse"})
    assert r.status_code == 302
    assert _user(app, "first")["role"] == "admin"


def test_second_account_is_a_plain_user(anon_client, app):
    anon_client.post("/register", data={
        "username": "first", "password": "correct-horse", "confirm": "correct-horse"})
    c2 = app.test_client()
    c2.post("/register", data={
        "username": "second", "password": "correct-horse", "confirm": "correct-horse"})
    assert _user(app, "second")["role"] == "user"


def test_registration_signs_you_in(anon_client):
    anon_client.post("/register", data={
        "username": "u", "password": "correct-horse", "confirm": "correct-horse"})
    assert anon_client.get("/").status_code == 200


@pytest.mark.parametrize("data,fragment", [
    ({"username": "", "password": "correct-horse", "confirm": "correct-horse"},
     b"Username is required"),
    ({"username": "u", "password": "short", "confirm": "short"},
     b"at least 10 characters"),
    ({"username": "u", "password": "correct-horse", "confirm": "different-one"},
     b"do not match"),
    ({"username": "u" * 61, "password": "correct-horse", "confirm": "correct-horse"},
     b"too long"),
])
def test_registration_validation(anon_client, data, fragment):
    r = anon_client.post("/register", data=data)
    assert r.status_code == 400
    assert fragment in r.data


def test_duplicate_username_is_rejected_case_insensitively(anon_client, app):
    anon_client.post("/register", data={
        "username": "Alice", "password": "correct-horse", "confirm": "correct-horse"})
    c2 = app.test_client()
    r = c2.post("/register", data={
        "username": "alice", "password": "correct-horse", "confirm": "correct-horse"})
    assert r.status_code == 409
    assert b"taken" in r.data


def test_registration_claims_the_bootstrap_owner(anon_client, app, admin_user):
    """Pre-accounts data belongs to the owner row; a parallel account would
    start with an empty reading list."""
    before = _count_users(app)
    anon_client.post("/register", data={
        "username": "santiago", "password": "correct-horse", "confirm": "correct-horse"})
    assert _count_users(app) == before          # adopted, not added
    u = _user(app, "santiago")
    assert u["id"] == admin_user and u["role"] == "admin"


# ── sign in / out ──────────────────────────────────────────────────────────────

def _register(c, username="u", password="correct-horse"):
    return c.post("/register", data={
        "username": username, "password": password, "confirm": password})


def test_login_with_correct_password(anon_client, app):
    _register(anon_client)
    anon_client.get("/logout")
    r = anon_client.post("/login", data={"username": "u", "password": "correct-horse"})
    assert r.status_code == 302
    assert anon_client.get("/").status_code == 200


def test_login_is_case_insensitive_on_username(anon_client):
    _register(anon_client, username="Alice")
    anon_client.get("/logout")
    assert anon_client.post(
        "/login", data={"username": "ALICE", "password": "correct-horse"}
    ).status_code == 302


@pytest.mark.parametrize("username,password", [
    ("u", "wrong-password-x"), ("nobody", "correct-horse"),
])
def test_bad_credentials_are_rejected(anon_client, username, password):
    _register(anon_client)
    anon_client.get("/logout")
    r = anon_client.post("/login", data={"username": username, "password": password})
    assert r.status_code == 401
    assert b"Wrong username or password" in r.data


def test_bootstrap_owner_cannot_be_logged_into(anon_client, admin_user):
    """Its hash is empty; an empty hash must never verify."""
    r = anon_client.post("/login", data={"username": "owner", "password": ""})
    assert r.status_code == 401


def test_logout_ends_the_session(anon_client):
    _register(anon_client)
    anon_client.get("/logout")
    assert anon_client.get("/").status_code == 302


def test_login_page_is_reachable_signed_out(anon_client):
    assert anon_client.get("/login").status_code == 200
    assert anon_client.get("/register").status_code == 200


def test_signed_in_users_skip_the_login_page(client):
    assert client.get("/login").status_code == 302
    assert client.get("/register").status_code == 302


# ── throttling ─────────────────────────────────────────────────────────────────

def test_repeated_failures_lock_the_account_out(anon_client, app):
    _register(anon_client)
    anon_client.get("/logout")
    from app.auth import MAX_FAILED_ATTEMPTS
    for _ in range(MAX_FAILED_ATTEMPTS):
        anon_client.post("/login", data={"username": "u", "password": "nope-nope-nope"})
    r = anon_client.post("/login", data={"username": "u", "password": "correct-horse"})
    assert r.status_code == 429
    assert b"Too many failed attempts" in r.data


def test_a_successful_login_clears_the_counter(anon_client, app):
    _register(anon_client)
    anon_client.get("/logout")
    anon_client.post("/login", data={"username": "u", "password": "wrong-one-xx"})
    anon_client.post("/login", data={"username": "u", "password": "correct-horse"})
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        assert db.execute(text("SELECT COUNT(*) FROM login_attempts")).scalar() == 0
        db.close()


# ── the gate ───────────────────────────────────────────────────────────────────

READER_PATHS = ["/", "/articles", "/count", "/sidebar/feeds", "/status", "/profile"]
ADMIN_PATHS = ["/settings", "/manage-feeds", "/admin/users",
               "/settings/ollama", "/settings/retention", "/feeds"]


@pytest.mark.parametrize("path", READER_PATHS + ADMIN_PATHS)
def test_everything_requires_a_session(anon_client, path):
    assert anon_client.get(path).status_code == 302


@pytest.mark.parametrize("path", READER_PATHS)
def test_plain_users_can_read(login_as, path):
    c, _ = login_as()
    assert c.get(path).status_code == 200


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_plain_users_are_refused_admin_pages(login_as, path):
    c, _ = login_as()
    assert c.get(path).status_code == 403


@pytest.mark.parametrize("path,data", [
    ("/poll", {}),
    ("/rescore-hidden", {}),
    ("/settings/titles", {}),
    ("/settings/retention", {"retention_days": "5"}),
    ("/feeds", {"url": "https://evil.test/rss"}),
])
def test_plain_users_are_refused_admin_actions(login_as, path, data):
    """Hiding a control in the template is not gating the route."""
    c, _ = login_as()
    assert c.post(path, data=data).status_code == 403


def test_plain_users_may_vote_and_save(login_as, app):
    from app.db import get_db_direct
    from tests.conftest import add_article, add_feed
    c, _ = login_as()
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db))
        db.close()
    assert c.post(f"/vote/{aid}/1").status_code == 200
    assert c.post(f"/article/{aid}/save").status_code == 200


def test_shared_profile_is_readable_by_all_but_writable_by_admins(login_as, client):
    c, _ = login_as()
    assert c.get("/preferences").status_code == 200
    assert c.post("/preferences", data={"profile_text": "sneaky"}).status_code == 403
    assert client.post("/preferences", data={"profile_text": "ok"}).status_code == 200


# ── HTMX behaviour ─────────────────────────────────────────────────────────────

def test_htmx_fragment_gets_401_and_redirect_header_not_a_login_page(anon_client):
    """A 302 here would swap the login page into #article-list."""
    r = anon_client.get("/articles", headers={"HX-Request": "true"})
    assert r.status_code == 401
    assert r.headers["HX-Redirect"] == "/login"
    assert b"<form" not in r.data


def test_htmx_admin_refusal_is_a_plain_403(login_as):
    c, _ = login_as()
    r = c.get("/settings/ollama", headers={"HX-Request": "true"})
    assert r.status_code == 403
    assert b"Admins only" in r.data


# ── per-user isolation ─────────────────────────────────────────────────────────

def test_one_users_dismiss_does_not_affect_another(login_as, client, app):
    from app.db import get_db_direct
    from tests.conftest import add_article, add_feed
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), title="Shared Story")
        db.close()
    other, _ = login_as()
    other.post(f"/article/{aid}/dismiss")
    assert b"Shared Story" not in other.get("/articles").data
    assert b"Shared Story" in client.get("/articles").data      # admin unaffected


def test_reading_lists_are_independent(login_as, client, app):
    from app.db import get_db_direct
    from tests.conftest import add_article, add_feed
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db))
        db.close()
    other, _ = login_as()
    other.get(f"/article/{aid}/content")                       # marks read for them
    assert client.get("/count").data == b"1"                   # still unread for admin


# ── profile ────────────────────────────────────────────────────────────────────

def test_profile_shows_account_and_activity(client):
    data = client.get("/profile").get_data(as_text=True)
    assert "Articles read" in data and "Votes cast" in data


def test_password_change_requires_the_current_one(anon_client):
    _register(anon_client)
    r = anon_client.post("/profile/password", data={
        "current_password": "wrong-one-xx", "new_password": "new-password-1",
        "confirm_password": "new-password-1"})
    assert b"Current password is wrong" in r.data


def test_password_change_works_and_the_new_one_signs_in(anon_client, app):
    _register(anon_client)
    r = anon_client.post("/profile/password", data={
        "current_password": "correct-horse", "new_password": "new-password-1",
        "confirm_password": "new-password-1"})
    assert b"Password changed" in r.data
    anon_client.get("/logout")
    assert anon_client.post(
        "/login", data={"username": "u", "password": "new-password-1"}
    ).status_code == 302


def test_password_change_validates_the_new_password(anon_client):
    _register(anon_client)
    r = anon_client.post("/profile/password", data={
        "current_password": "correct-horse", "new_password": "short",
        "confirm_password": "short"})
    assert b"at least 10 characters" in r.data


# ── forced password change ─────────────────────────────────────────────────────

def test_forced_change_blocks_everything_else(login_as):
    c, _ = login_as(must_change_password=True)
    assert c.get("/articles").status_code == 302
    assert c.get("/profile").status_code == 200          # except the profile


def test_forced_change_needs_no_current_password(login_as):
    c, _ = login_as(must_change_password=True)
    r = c.post("/profile/password", data={
        "new_password": "brand-new-pass", "confirm_password": "brand-new-pass"})
    assert b"Password changed" in r.data
    assert c.get("/articles").status_code == 200         # released


# ── admin user management ──────────────────────────────────────────────────────

def test_admin_can_promote_and_demote(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="member", role="user")
        db.close()
    client.post(f"/admin/users/{uid}/role", data={"role": "admin"})
    assert _user(app, "member")["role"] == "admin"
    client.post(f"/admin/users/{uid}/role", data={"role": "user"})
    assert _user(app, "member")["role"] == "user"


def test_last_admin_cannot_be_demoted(client, admin_user, app):
    r = client.post(f"/admin/users/{admin_user}/role", data={"role": "user"})
    assert b"last admin" in r.data
    from app.repo.users import get
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        assert get(db, admin_user)["role"] == "admin"
        db.close()


def test_last_admin_cannot_be_deleted(client, admin_user, app):
    r = client.post(f"/admin/users/{admin_user}/delete")
    assert b"last admin" in r.data
    assert _count_users(app) == 1


def test_admin_cannot_delete_themselves(client, admin_user, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_user(db, username="other-admin", role="admin")   # so we're not the last
        db.close()
    r = client.post(f"/admin/users/{admin_user}/delete")
    assert b"cannot delete your own account" in r.data


def test_admin_can_delete_another_user(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="gone", role="user")
        db.close()
    client.post(f"/admin/users/{uid}/delete")
    assert _user(app, "gone") is None


def test_invalid_role_is_rejected(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="member", role="user")
        db.close()
    assert client.post(f"/admin/users/{uid}/role",
                       data={"role": "superuser"}).status_code == 400


@pytest.mark.parametrize("path", ["role", "delete", "reset-password"])
def test_actions_on_unknown_users_404(client, path):
    assert client.post(f"/admin/users/999999/{path}",
                       data={"role": "user"}).status_code == 404


def test_password_reset_shows_the_temporary_once_and_forces_a_change(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="member", role="user")
        db.close()
    r = client.post(f"/admin/users/{uid}/reset-password")
    assert b"Temporary password" in r.data
    assert b"Shown once" in r.data
    from app.repo.users import get
    with app.app_context():
        db = get_db_direct()
        assert get(db, uid)["must_change_password"] is True
        db.close()


def test_reset_accepts_an_explicit_password_and_it_works(anon_client, client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="member", role="user")
        db.close()
    client.post(f"/admin/users/{uid}/reset-password",
                data={"temp_password": "temporary-1234"})
    r = anon_client.post("/login",
                         data={"username": "member", "password": "temporary-1234"})
    assert r.status_code == 302
    assert anon_client.get("/articles").status_code == 302   # forced to change first


def test_reset_rejects_a_weak_explicit_password(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="member", role="user")
        db.close()
    r = client.post(f"/admin/users/{uid}/reset-password", data={"temp_password": "abc"})
    assert b"at least 10 characters" in r.data


def test_generated_passwords_are_long_and_unique():
    from app.repo.users import generate_password
    a, b = generate_password(), generate_password()
    assert len(a) >= 14 and a != b


def test_empty_password_is_rejected():
    from app.auth import password_problem
    assert password_problem("") == "Password is required."
    assert password_problem("plenty-long-enough") is None


def test_decorators_guard_independently_of_the_before_request_hook(app):
    """Defence in depth: the hook already redirects, but a route must not rely
    on it — a future PUBLIC_ENDPOINTS entry would otherwise expose it."""
    from app.auth import admin_required, login_required
    guarded_any = login_required(lambda: "reader ok")
    guarded_admin = admin_required(lambda: "admin ok")
    with app.test_request_context("/"):
        assert guarded_any().status_code == 302        # no session at all
        assert guarded_admin().status_code == 302


def test_admin_sees_the_user_list(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_user(db, username="member", role="user")
        db.close()
    data = client.get("/admin/users").get_data(as_text=True)
    assert "member" in data
    assert "Users" in data

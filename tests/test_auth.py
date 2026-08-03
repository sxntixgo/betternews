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
    # `/api/v1/me`, not `/`: the index is the SPA now, served ahead of Flask.
    # This asks the session the question directly rather than through a page.
    assert anon_client.get("/api/v1/me").status_code == 200


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
    assert r.headers["Location"] == "/", "lands on the SPA"
    assert anon_client.get("/api/v1/me").status_code == 200


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
    assert anon_client.get("/logout").headers["Location"] == "/login"
    assert anon_client.get("/api/v1/me").status_code == 401


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


def test_a_readers_profile_is_built_from_their_own_votes_only(app):
    """The regeneration read the whole votes table with no user filter."""
    from unittest.mock import patch
    from app.db import get_db_direct
    from app.pipeline import regenerate_preferences
    from app.repo.articles import record_vote
    from app.repo.users import ensure_bootstrap_user
    from tests.conftest import add_article, add_feed, add_user
    from sqlalchemy import text

    with app.app_context():
        db = get_db_direct()
        owner = ensure_bootstrap_user(db)
        stranger = add_user(db, "stranger")
        fid = add_feed(db)
        mine = add_article(db, fid, seq=1, guid="mine", title="Mine")
        theirs = add_article(db, fid, seq=2, guid="theirs", title="Theirs")
        record_vote(db, owner, mine, 1)
        record_vote(db, stranger, theirs, 1)
        db.commit()
        db.close()

    seen = []
    with patch("app.ollama_client.generate",
               side_effect=lambda **kw: seen.append(kw["prompt"]) or "a profile"):
        regenerate_preferences(app, user_id=1 if False else None)

    assert len(seen) == 2, "one profile per voting reader"
    owners_prompt = next(p for p in seen if "Mine" in p)
    assert "Theirs" not in owners_prompt, "another reader's votes leaked in"


# ── HTMX behaviour ─────────────────────────────────────────────────────────────


# ── per-user isolation ─────────────────────────────────────────────────────────


# ── profile ────────────────────────────────────────────────────────────────────


# ── forced password change ─────────────────────────────────────────────────────


# ── admin user management ──────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["role", "delete", "reset-password"])
def test_actions_on_unknown_users_404(client, path):
    assert client.post(f"/admin/users/999999/{path}",
                       data={"role": "user"}).status_code == 404


def test_generated_passwords_are_long_and_unique():
    from app.repo.users import generate_password
    a, b = generate_password(), generate_password()
    assert len(a) >= 14 and a != b


def test_empty_password_is_rejected():
    from app.auth import password_problem
    assert password_problem("") == "Password is required."
    assert password_problem("plenty-long-enough") is None


# ── signed-out pages must not call authenticated endpoints ────────────────────

AUTHED_ENDPOINTS = ("/sidebar/feeds", "/articles", "/count", "/digest", "/status")


@pytest.mark.parametrize("path", ["/login", "/register"])
def test_signed_out_pages_do_not_fetch_authenticated_endpoints(anon_client, path):
    """A redirect loop, not a cosmetic issue.

    base.html loads #sidebar-feeds via hx-trigger="load". On a signed-out page
    that request answers 401 + HX-Redirect: /login, HTMX navigates the window to
    /login, and /login renders the sidebar again — forever.
    """
    body = anon_client.get(path).get_data(as_text=True)
    for endpoint in AUTHED_ENDPOINTS:
        assert f'"{endpoint}"' not in body, f"{path} still references {endpoint}"
    assert "hx-trigger=\"load" not in body


@pytest.mark.parametrize("path", ["/login", "/register"])
def test_signed_out_pages_render_without_the_sidebar(anon_client, path):
    body = anon_client.get(path).get_data(as_text=True)
    assert 'id="sidebar-feeds"' not in body
    assert "site-layout-bare" in body


def test_login_page_returns_200_not_a_redirect(anon_client):
    """The reported symptom: /login redirecting to /login."""
    r = anon_client.get("/login")
    assert r.status_code == 200
    assert "Location" not in r.headers


def test_htmx_request_to_login_is_not_redirected(anon_client):
    """If HTMX somehow asks for /login, answering with another HX-Redirect to
    /login is what closes the loop."""
    r = anon_client.get("/login", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "HX-Redirect" not in r.headers


# ── API tokens on the profile page ────────────────────────────────────────────



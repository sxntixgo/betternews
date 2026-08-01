"""Accounts, sessions and role gating.

Registration is open and **the first account created becomes admin**; every
later one is a plain user. The count and the insert happen in one transaction
with the table locked, so two simultaneous first registrations cannot both win.

Session state is a signed cookie holding only the user id. Everything else is
read from the database per request, so a role change or a deletion takes effect
immediately rather than when the cookie expires.
"""

import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Response, current_app, g, redirect, render_template, request, session, url_for,
)
from sqlalchemy import func, select, text
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import get_db
from app.models import login_attempts as LA
from app.models import users as U
from app.repo import users as user_repo

log = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 10
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# Reachable without a session. The two static PWA files must stay open or the
# app stops being installable.
PUBLIC_ENDPOINTS = {
    "main.login", "main.login_post",
    "main.register", "main.register_post",
    "main.logout", "main.healthcheck", "static",
}


# ── password rules ─────────────────────────────────────────────────────────────

def password_problem(password: str, confirm: str | None = None) -> str | None:
    """Return a human-readable problem, or None if the password is acceptable."""
    if not password:
        return "Password is required."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if confirm is not None and password != confirm:
        return "Passwords do not match."
    return None


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    # An empty hash is the bootstrap owner row, which cannot be logged into.
    if not stored_hash:
        return False
    return check_password_hash(stored_hash, password)


# ── throttling ─────────────────────────────────────────────────────────────────

def _attempt_key(username: str) -> str:
    return (username or "").strip().lower()


def is_locked_out(db, username: str) -> bool:
    """Backoff lives in Postgres, not process memory — it has to hold across
    gunicorn workers."""
    row = db.execute(
        select(LA.c.failures, LA.c.last_failure_at)
        .where(LA.c.username == _attempt_key(username))
    ).first()
    if not row or row[0] < MAX_FAILED_ATTEMPTS or not row[1]:
        return False
    return row[1] > datetime.now(timezone.utc) - timedelta(minutes=LOCKOUT_MINUTES)


def record_failure(db, username: str) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(LA).values(
        username=_attempt_key(username), failures=1, last_failure_at=func.now()
    )
    db.execute(stmt.on_conflict_do_update(
        index_elements=[LA.c.username],
        set_={"failures": LA.c.failures + 1, "last_failure_at": func.now()},
    ))


def clear_failures(db, username: str) -> None:
    db.execute(LA.delete().where(LA.c.username == _attempt_key(username)))


# ── session ────────────────────────────────────────────────────────────────────

def login_user(db, user_id: int) -> None:
    session.clear()            # rotate: never carry state across an identity change
    session["user_id"] = user_id
    session.permanent = True
    db.execute(U.update().where(U.c.id == user_id).values(last_login_at=func.now()))


def logout_user() -> None:
    session.clear()


def current_user():
    """The acting user for this request, or None. Cached per request."""
    if "current_user" not in g:
        uid = session.get("user_id")
        g.current_user = user_repo.get(get_db(), uid) if uid else None
    return g.current_user


def current_user_id() -> int | None:
    u = current_user()
    return u["id"] if u else None


def is_admin() -> bool:
    u = current_user()
    return bool(u and u["role"] == "admin")


# ── responses ──────────────────────────────────────────────────────────────────

def _redirect_to(endpoint: str):
    """HTMX-aware redirect.

    A fragment request that hits an expired session must not get a login page
    swapped into #article-list. HTMX honours HX-Redirect on a 401 and navigates
    the whole window instead.
    """
    target = url_for(endpoint)
    if request.headers.get("HX-Request"):
        r = Response("", status=401)
        r.headers["HX-Redirect"] = target
        return r
    return redirect(target)


def _forbidden():
    if request.headers.get("HX-Request"):
        return Response("Admins only.", status=403)
    return render_template("403.html"), 403


# ── decorators ─────────────────────────────────────────────────────────────────

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return _redirect_to("main.login")
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return _redirect_to("main.login")
        if not is_admin():
            return _forbidden()
        return fn(*args, **kwargs)
    return wrapper


# ── request hooks ──────────────────────────────────────────────────────────────

def install(app) -> None:
    # Assigned, not setdefault. Flask's default config already *contains* these
    # keys, so setdefault never fired and the SameSite value it appeared to set
    # was silently dropped -- the cookie went out with no SameSite attribute at
    # all. HttpOnly only looked correct because Flask's own default is True.
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    # Strict, not Lax. This is what lets the JSON API accept a session cookie
    # at all: a cross-site request does not carry the cookie, so there is no
    # confused deputy to protect against and no CSRF token to manage. Lax would
    # already block cross-site POSTs, but the API is read-heavy and a GET that
    # returns a reader's articles is worth the same protection.
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    # Long-lived so the phone stays signed in between reading sessions.
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(days=90))
    app.before_request(_require_session)
    app.before_request(_force_password_change)


def _is_api_request() -> bool:
    """The JSON API authenticates itself and must never be redirected.

    These hooks run app-wide, before any blueprint. Without this the session
    guard answered every /api/v1 call with a 302 to /login -- even one carrying
    a perfectly good bearer token -- and a native client saw a redirect to an
    HTML page instead of its data.
    """
    return (request.blueprint == "api"
            or request.path.startswith("/api/"))


def _require_session():
    if _is_api_request():
        return None
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if current_user() is None:
        return _redirect_to("main.login")
    return None


def _force_password_change():
    """After an admin reset, nothing else is reachable until it's changed."""
    if _is_api_request():
        # A token client cannot complete a password change, and bouncing it to
        # an HTML form would be a redirect it cannot follow.
        return None
    u = current_user()
    if not u or not u["must_change_password"]:
        return None
    allowed = {"main.profile", "main.profile_password", "main.logout", "static"}
    if request.endpoint in allowed or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    return _redirect_to("main.profile")


# ── registration ───────────────────────────────────────────────────────────────

def register_user(db, username: str, password: str) -> int:
    """Create an account. The first one created is an admin.

    Locks `users` for the duration so the "am I first?" check and the insert
    cannot interleave with a concurrent registration.
    """
    db.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
    existing = db.execute(select(func.count()).select_from(U)).scalar_one()

    # The bootstrap owner row holds all pre-accounts data. Claim it rather than
    # creating a parallel account that would see an empty reading list.
    orphan = db.execute(
        select(U.c.id).where(U.c.password_hash == "").order_by(U.c.id).limit(1)
    ).scalar()
    if orphan is not None:
        db.execute(U.update().where(U.c.id == orphan).values(
            username=username.strip(), password_hash=hash_password(password),
            role="admin", must_change_password=False,
        ))
        return orphan

    return db.execute(
        U.insert().values(
            username=username.strip(),
            password_hash=hash_password(password),
            role="admin" if existing == 0 else "user",
        ).returning(U.c.id)
    ).scalar_one()


def count_admins(db) -> int:
    return db.execute(
        select(func.count()).select_from(U).where(U.c.role == "admin")
    ).scalar_one()

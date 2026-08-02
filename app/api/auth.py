"""Signing in with a password, for clients that can hold a cookie.

The browser never sees a credential: it posts a username and password once and
gets an HttpOnly session cookie back. Nothing to store, nothing for injected
script to read, nothing to leak in a screenshot.

A phone still uses a bearer token from Profile -> API tokens, because a native
client cannot hold a cookie usefully.
"""

from flask import jsonify, request

from app import auth as auth_mod
from app.api import bp, error
from app.db import get_db
from app.repo import users as user_repo


@bp.post("/auth/login")
def login():
    db = get_db()
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        return error("Username and password are required.", 400)

    # The same lockout the HTML form uses. A second password path with its own
    # rules is how brute-force protection quietly stops applying to half the
    # front door.
    if auth_mod.is_locked_out(db, username):
        return error("Too many failed attempts. Try again shortly.", 429)

    user = user_repo.by_username(db, username)
    if not user or not auth_mod.verify_password(user["password_hash"], password):
        auth_mod.record_failure(db, username)
        db.commit()
        # One message for both cases: a different answer for "no such user"
        # turns this into a way to enumerate accounts.
        return error("Wrong username or password.", 401)

    auth_mod.clear_failures(db, username)
    auth_mod.login_user(db, user["id"])
    db.commit()
    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        # Reported, not enforced. After an admin reset the HTML UI blocks
        # everything until the password changes, but the API has no form to send
        # anyone to, and refusing the login would strand the reader with no way
        # to fix it. The client decides what to do; the endpoint to act on it
        # arrives with the rest of the profile screens.
        "must_change_password": bool(user["must_change_password"]),
    })


@bp.post("/auth/register")
def register():
    """Create an account. The first one on an empty instance is the admin.

    Same rules as the HTML form, and the same lock inside register_user so the
    "am I first?" check cannot interleave with a concurrent registration.
    """
    db = get_db()
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    confirm = body.get("confirm", password)

    if not username:
        return error("Username is required.", 400)
    if len(username) > 60:
        return error("Username is too long.", 400)
    problem = auth_mod.password_problem(password, confirm)
    if problem:
        return error(problem, 400)
    if user_repo.by_username(db, username):
        return error("That username is taken.", 409)

    uid = auth_mod.register_user(db, username, password)
    auth_mod.login_user(db, uid)
    db.commit()
    user = user_repo.get(db, uid)
    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "must_change_password": bool(user["must_change_password"]),
    })


@bp.post("/auth/logout")
def logout():
    """Ends the session. Safe to call when not signed in."""
    auth_mod.logout_user()
    return jsonify({"ok": True})

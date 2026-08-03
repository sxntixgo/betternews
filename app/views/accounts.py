"""Sign in and registration.

The last reader-facing HTML. A browser arriving with no session needs somewhere
to land that does not depend on the bundle having loaded -- if the SPA were the
only way in, a broken build would lock everyone out with no way to tell whether
the server was even up.

Everything else a reader does, profile included, is `/api/v1/me/*`.
"""

import logging

from flask import redirect, render_template, request

from app import auth
from app.db import get_db
from app.repo import users as user_repo

from app.views import bp


log = logging.getLogger(__name__)


@bp.get("/login")
def login():
    if auth.current_user():
        return redirect("/")
    db = get_db()
    return render_template("login.html", first_run=user_repo.count(db) == 0)


@bp.post("/login")
def login_post():
    db = get_db()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if auth.is_locked_out(db, username):
        return render_template(
            "login.html", error="Too many failed attempts. Try again shortly.",
            username=username, first_run=False), 429

    user = user_repo.by_username(db, username)
    if not user or not auth.verify_password(user["password_hash"], password):
        auth.record_failure(db, username)
        db.commit()
        return render_template(
            "login.html", error="Wrong username or password.",
            username=username, first_run=user_repo.count(db) == 0), 401

    auth.clear_failures(db, username)
    auth.login_user(db, user["id"])
    db.commit()
    return redirect("/")


@bp.get("/register")
def register():
    if auth.current_user():
        return redirect("/")
    db = get_db()
    return render_template("register.html", first_run=user_repo.count(db) == 0)


@bp.post("/register")
def register_post():
    db = get_db()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    first_run = user_repo.count(db) == 0

    def fail(msg, code=400):
        return render_template("register.html", error=msg, username=username,
                               first_run=first_run), code

    if not username:
        return fail("Username is required.")
    if len(username) > 60:
        return fail("Username is too long.")
    problem = auth.password_problem(password, confirm)
    if problem:
        return fail(problem)
    if user_repo.by_username(db, username):
        return fail("That username is taken.", 409)

    uid = auth.register_user(db, username, password)
    auth.login_user(db, uid)
    db.commit()
    log.info("Registered user %r (id=%d)", username, uid)
    return redirect("/")


@bp.post("/logout")
@bp.get("/logout")
def logout():
    auth.logout_user()
    return redirect("/login")

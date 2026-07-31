"""Sign in, registration and a reader's own profile."""

import logging
from app import (api_tokens, auth, call_log, digest as digest_mod, export as export_mod,
                 extract, health, insights, pipeline_status, retention,
                 topics as topics_mod, user_topics)
from app.db import get_db, get_setting, set_setting
from app.repo import articles as art_repo, users as user_repo
from flask import (Blueprint, current_app, g, redirect, render_template,
                   request, Response, url_for)
from sqlalchemy import text as sql

from app.views import bp, current_user_id


log = logging.getLogger(__name__)


@bp.get("/login")
def login():
    if auth.current_user():
        return redirect(url_for("main.index"))
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
    return redirect(url_for("main.index"))


@bp.get("/register")
def register():
    if auth.current_user():
        return redirect(url_for("main.index"))
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
    return redirect(url_for("main.index"))


@bp.post("/logout")
@bp.get("/logout")
def logout():
    auth.logout_user()
    return redirect(url_for("main.login"))


@bp.get("/profile")
@auth.login_required
def profile():
    db = get_db()
    user = auth.current_user()
    return render_template("profile.html", user=user,
                           stats=user_repo.stats(db, user["id"]),
                           tokens=api_tokens.for_user(db, user["id"]))


@bp.get("/profile/topics")
@auth.login_required
def profile_topics():
    db = get_db()
    uid = current_user_id(db)
    return render_template("_user_topics.html",
                           rows=user_topics.for_profile(db, uid),
                           hints=user_topics.suggestions(db, uid))


@bp.post("/profile/topics")
@auth.login_required
def profile_topics_save():
    """Set one topic's stance. Shapes this user's list only."""
    db = get_db()
    uid = current_user_id(db)
    topic = request.form.get("topic", "").strip()
    stance = request.form.get("stance", "").strip()
    try:
        if stance == "clear":
            user_topics.set_stance(db, uid, topic, None)
        elif stance == "reset-all":
            user_topics.clear_all(db, uid)
        else:
            user_topics.set_stance(db, uid, topic, stance)
    except ValueError as exc:
        return render_template("_user_topics.html",
                               rows=user_topics.for_profile(db, uid),
                               hints=user_topics.suggestions(db, uid),
                               error=str(exc))
    db.commit()
    # The digest covers unread articles, so a stance change invalidates it.
    digest_mod.clear(db, uid)
    db.commit()
    return render_template("_user_topics.html",
                           rows=user_topics.for_profile(db, uid),
                           hints=user_topics.suggestions(db, uid), saved=True)


@bp.post("/profile/password")
@auth.login_required
def profile_password():
    db = get_db()
    user = auth.current_user()
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    def render(error=None, saved=False):
        return render_template("_profile_password.html", error=error, saved=saved,
                               must_change=user["must_change_password"])

    # A forced change has no working current password to prove.
    if not user["must_change_password"] and not auth.verify_password(
            user["password_hash"], current):
        return render(error="Current password is wrong.")
    problem = auth.password_problem(new, confirm)
    if problem:
        return render(error=problem)

    db.execute(sql(
        "UPDATE users SET password_hash=:h, must_change_password=false WHERE id=:id"),
        {"h": auth.hash_password(new), "id": user["id"]})
    db.commit()
    g.pop("current_user", None)
    return render(saved=True)


def _token_panel(db, uid, **kw):
    return render_template("_api_tokens.html",
                           tokens=api_tokens.for_user(db, uid), **kw)


@bp.post("/profile/tokens")
@auth.login_required
def profile_token_create():
    """Issue a token. Shown once, here, and never again."""
    db = get_db()
    uid = current_user_id(db)
    name = request.form.get("name", "").strip()
    if not name:
        return _token_panel(db, uid, error="Give the device a name.")
    token = api_tokens.issue(db, uid, name)
    db.commit()
    return _token_panel(db, uid, new_token=token)


@bp.post("/profile/tokens/<int:token_id>/revoke")
@auth.login_required
def profile_token_revoke(token_id: int):
    db = get_db()
    uid = current_user_id(db)
    # Scoped to this user inside revoke(); the id arrives from a form.
    api_tokens.revoke(db, uid, token_id)
    db.commit()
    return _token_panel(db, uid)


# ── the reader's own interest profile ─────────────────────────────────────────

def _profile_panel(db, uid, **kw):
    """The profile plus the evidence behind it.

    Prose alone reads as vague however specific it is, because there is no way
    to tell what produced it. Showing the counts and the stances next to it is
    the difference between "a paragraph appeared" and "this is what my 38 votes
    and my stated topics add up to".
    """
    row = db.execute(sql(
        "SELECT profile_text, updated_at FROM preferences WHERE user_id = :u"
    ), {"u": uid}).mappings().first()
    counts = db.execute(sql(
        "SELECT count(*) FILTER (WHERE value = 1)  AS liked, "
        "       count(*) FILTER (WHERE value = -1) AS disliked "
        "FROM votes WHERE user_id = :u"), {"u": uid}).mappings().first()
    stances = db.execute(sql(
        "SELECT topic, stance FROM user_topic_prefs WHERE user_id = :u "
        "ORDER BY topic"), {"u": uid}).mappings().all()
    return render_template(
        "_preferences.html",
        profile_text=row["profile_text"] if row else "",
        updated_at=row["updated_at"] if row else None,
        liked=counts["liked"], disliked=counts["disliked"],
        boosted=[r["topic"] for r in stances if r["stance"] == "more"],
        hidden=[r["topic"] for r in stances if r["stance"] == "hide"],
        **kw,
    )


@bp.get("/profile/preferences")
@auth.login_required
def preferences_get():
    db = get_db()
    return _profile_panel(db, current_user_id(db))


@bp.post("/profile/preferences")
@auth.login_required
def preferences_save():
    """Anyone may edit their own. It used to be admin-only because there was
    one profile for everybody; now it is nobody else's business."""
    db = get_db()
    uid = current_user_id(db)
    body = request.form.get("profile_text", "").strip()
    db.execute(sql(
        """INSERT INTO preferences (user_id, profile_text, updated_at)
           VALUES (:u, :profile, now())
           ON CONFLICT (user_id) DO UPDATE
             SET profile_text = EXCLUDED.profile_text,
                 updated_at   = EXCLUDED.updated_at"""),
        {"u": uid, "profile": body},
    )
    db.commit()
    return _profile_panel(db, uid, saved=True)


@bp.post("/profile/preferences/regenerate")
@auth.login_required
def preferences_regenerate():
    import threading
    from app.pipeline import regenerate_preferences

    app = current_app._get_current_object()
    uid = current_user_id(get_db())

    def _run():
        try:
            # Scoped to this reader: regenerating everyone's from one button
            # would rewrite a profile its owner never asked to change.
            regenerate_preferences(app, user_id=uid)
        except Exception as exc:
            log.error("Manual preference regeneration failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
    return Response("ok", status=200)

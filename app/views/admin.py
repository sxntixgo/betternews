"""User administration. Every route here is @admin_required."""

import logging
from app import (auth, call_log, digest as digest_mod, export as export_mod,
                 extract, health, insights, pipeline_status, retention,
                 topics as topics_mod, user_topics)
from app.db import get_db, get_setting, set_setting
from app.repo import articles as art_repo, users as user_repo
from flask import (Blueprint, current_app, g, redirect, render_template,
                   request, Response, url_for)
from sqlalchemy import text as sql

from app.views import bp


log = logging.getLogger(__name__)


@bp.get("/admin/users")
@auth.admin_required
def admin_users():
    db = get_db()
    return render_template("admin_users.html", users=user_repo.all_with_stats(db),
                           me=auth.current_user_id())


def _users_fragment(db, **kw):
    return render_template("_admin_user_rows.html", users=user_repo.all_with_stats(db),
                           me=auth.current_user_id(), **kw)


@bp.post("/admin/users/<int:user_id>/reset-password")
@auth.admin_required
def admin_reset_password(user_id: int):
    """Set a temporary password, shown once, and force a change at next login."""
    db = get_db()
    target = user_repo.get(db, user_id)
    if not target:
        return Response("no such user", status=404)
    temp = request.form.get("temp_password", "").strip() or user_repo.generate_password()
    problem = auth.password_problem(temp)
    if problem:
        return _users_fragment(db, error=problem)
    db.execute(sql(
        "UPDATE users SET password_hash=:h, must_change_password=true WHERE id=:id"),
        {"h": auth.hash_password(temp), "id": user_id})
    db.commit()
    log.info("Admin reset password for user id=%d", user_id)
    return _users_fragment(db, temp_password=temp, temp_for=target["username"])


@bp.post("/admin/users/<int:user_id>/role")
@auth.admin_required
def admin_set_role(user_id: int):
    db = get_db()
    role = request.form.get("role", "")
    if role not in ("user", "admin"):
        return Response("invalid role", status=400)
    target = user_repo.get(db, user_id)
    if not target:
        return Response("no such user", status=404)
    # Locking the row keeps two simultaneous demotions from leaving zero admins.
    db.execute(sql("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
    if role == "user" and target["role"] == "admin" and auth.count_admins(db) <= 1:
        return _users_fragment(db, error="That is the last admin — promote someone else first.")
    db.execute(sql("UPDATE users SET role=:r WHERE id=:id"), {"r": role, "id": user_id})
    db.commit()
    return _users_fragment(db)


@bp.post("/admin/users/<int:user_id>/delete")
@auth.admin_required
def admin_delete_user(user_id: int):
    db = get_db()
    target = user_repo.get(db, user_id)
    if not target:
        return Response("no such user", status=404)
    db.execute(sql("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
    if target["role"] == "admin" and auth.count_admins(db) <= 1:
        return _users_fragment(db, error="That is the last admin — promote someone else first.")
    if user_id == auth.current_user_id():
        return _users_fragment(db, error="You cannot delete your own account.")
    db.execute(sql("DELETE FROM users WHERE id=:id"), {"id": user_id})
    db.commit()
    log.info("Admin deleted user id=%d (%s)", user_id, target["username"])
    return _users_fragment(db)

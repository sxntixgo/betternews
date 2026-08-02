"""The reader's own account: password, devices, and their interest profile.

Everything here is scoped to the caller. An id in a URL is a request, not a
permission — `/me/tokens/<id>/revoke` answers 404 for someone else's token
rather than 403, because whether it exists is not the caller's business either.
"""

from flask import jsonify, request
from sqlalchemy import text as sql

from app import api_tokens, auth as auth_mod, user_topics
from app.api import api_auth, bp, current_api_user, error
from app.db import get_db
from app.repo import users as user_repo


@bp.post("/me/password")
@api_auth
def change_password():
    db = get_db()
    uid = current_api_user()
    user = user_repo.get(db, uid)
    body = request.get_json(silent=True) or {}
    current = body.get("current") or ""
    new = body.get("new") or ""
    confirm = body.get("confirm") or ""

    # A forced change has no working current password to prove — the same
    # exception the HTML form makes, for the same reason.
    if not user["must_change_password"]:
        if not auth_mod.verify_password(user["password_hash"], current):
            return error("Current password is wrong.", 400)

    problem = auth_mod.password_problem(new, confirm)
    if problem:
        return error(problem, 400)

    db.execute(sql(
        "UPDATE users SET password_hash = :h, must_change_password = false "
        "WHERE id = :i"), {"h": auth_mod.hash_password(new), "i": uid})
    db.commit()
    return jsonify({"ok": True})


@bp.get("/me/tokens")
@api_auth
def list_tokens():
    """Live devices. Never the token values — those exist once, at creation."""
    db = get_db()
    rows = api_tokens.for_user(db, current_api_user())
    return jsonify({"tokens": [
        {"id": r["id"], "name": r["name"],
         "created_at": r["created_at"].isoformat() if r["created_at"] else None,
         "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None}
        for r in rows
    ]})


@bp.post("/me/tokens")
@api_auth
def create_token():
    db = get_db()
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    if not name:
        return error("Give the device a name.", 400)
    value = api_tokens.issue(db, current_api_user(), name)
    db.commit()
    # The only time the value is ever returned.
    return jsonify({"token": value, "name": name[:60]})


@bp.post("/me/tokens/<int:token_id>/revoke")
@api_auth
def revoke_token(token_id: int):
    db = get_db()
    if not api_tokens.revoke(db, current_api_user(), token_id):
        return error("No such device.", 404)
    db.commit()
    return jsonify({"ok": True})


@bp.get("/me/preferences")
@api_auth
def get_preferences():
    """The profile, with the evidence behind it.

    Prose alone reads as vague however specific it is, because nothing says what
    produced it — so the counts and stances travel with it.
    """
    db = get_db()
    uid = current_api_user()
    row = db.execute(sql(
        "SELECT profile_text, updated_at FROM preferences WHERE user_id = :u"
    ), {"u": uid}).mappings().first()
    counts = db.execute(sql(
        "SELECT count(*) FILTER (WHERE value = 1)  AS liked, "
        "       count(*) FILTER (WHERE value = -1) AS disliked "
        "FROM votes WHERE user_id = :u"), {"u": uid}).mappings().first()
    stances = user_topics.stances(db, uid)
    return jsonify({
        "profile_text": row["profile_text"] if row else "",
        "updated_at": row["updated_at"].isoformat() if row and row["updated_at"] else None,
        "liked": counts["liked"],
        "disliked": counts["disliked"],
        "stances": stances,
    })


@bp.post("/me/preferences")
@api_auth
def save_preferences():
    db = get_db()
    uid = current_api_user()
    body = (request.get_json(silent=True) or {}).get("profile_text", "").strip()
    db.execute(sql(
        """INSERT INTO preferences (user_id, profile_text, updated_at)
           VALUES (:u, :p, now())
           ON CONFLICT (user_id) DO UPDATE
             SET profile_text = EXCLUDED.profile_text,
                 updated_at   = EXCLUDED.updated_at"""),
        {"u": uid, "p": body})
    db.commit()
    return jsonify({"profile_text": body})


@bp.post("/me/preferences/regenerate")
@api_auth
def regenerate_preferences():
    """Rebuild this reader's profile from their own votes and stances.

    Scoped to the caller: regenerating everyone's from one button would rewrite
    a profile its owner never asked to change.
    """
    import threading

    from flask import current_app
    from app.pipeline import regenerate_preferences as regen

    app_obj = current_app._get_current_object()
    uid = current_api_user()

    def _run():
        try:
            regen(app_obj, user_id=uid)
        except Exception as exc:                       # pragma: no cover - logged
            from app.api import log
            log.error("API preference regeneration failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"started": True})

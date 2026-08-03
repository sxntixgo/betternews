"""User administration, ranking insights, and the Ollama call log.

The last three HTML-only areas. Everything here is `@api_admin`.

The guard rails from the HTML side are re-implemented, not re-used: those
routes return HTML fragments and take form fields, so sharing them would mean
returning a fragment to a phone. What must not diverge is the *rules* -- you
cannot demote the last admin, and you cannot delete yourself -- so those are
asserted against both front ends in `tests/test_api.py`.
"""

import logging

from flask import jsonify, request
from sqlalchemy import text as sql

from app import auth as session_auth, call_log, insights, pipeline_status
from app.api import api_admin, bp, error
from app.db import get_db, get_setting, set_setting
from app.repo import users as user_repo

log = logging.getLogger(__name__)


def _user_row(r) -> dict:
    return {
        "id": r["id"],
        "username": r["username"],
        "role": r["role"],
        "must_change_password": bool(r["must_change_password"]),
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "last_login_at": r["last_login_at"].isoformat() if r["last_login_at"] else None,
        "votes": r["votes"],
        "read_count": r["read_count"],
    }


def _users(db):
    return jsonify({
        "users": [_user_row(r) for r in user_repo.all_with_stats(db)],
        # Who "you" are matters to the client: it has to refuse to offer delete
        # on your own row, and the server refuses it anyway.
        "me": session_auth.current_user_id(),
    })


@bp.get("/admin/users")
@api_admin
def users_list():
    return _users(get_db())


@bp.post("/admin/users/<int:user_id>/role")
@api_admin
def set_role(user_id: int):
    db = get_db()
    role = (request.get_json(silent=True) or {}).get("role", "")
    if role not in ("user", "admin"):
        return error("role must be 'user' or 'admin'.", 400)
    target = user_repo.get(db, user_id)
    if not target:
        return error("No such user.", 404)
    # Locking the row keeps two simultaneous demotions from leaving zero admins.
    # The HTML route does the same; an instance with no admin cannot be repaired
    # from inside the app.
    db.execute(sql("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
    if role == "user" and target["role"] == "admin" and session_auth.count_admins(db) <= 1:
        return error("That is the last admin — promote someone else first.", 409)
    db.execute(sql("UPDATE users SET role=:r WHERE id=:id"), {"r": role, "id": user_id})
    db.commit()
    return _users(db)


@bp.post("/admin/users/<int:user_id>/delete")
@api_admin
def delete_user(user_id: int):
    db = get_db()
    target = user_repo.get(db, user_id)
    if not target:
        return error("No such user.", 404)
    db.execute(sql("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
    if target["role"] == "admin" and session_auth.count_admins(db) <= 1:
        return error("That is the last admin — promote someone else first.", 409)
    if user_id == session_auth.current_user_id():
        return error("You cannot delete your own account.", 409)
    db.execute(sql("DELETE FROM users WHERE id=:id"), {"id": user_id})
    db.commit()
    log.info("Admin deleted user id=%d (%s)", user_id, target["username"])
    return _users(db)


@bp.post("/admin/users/<int:user_id>/reset-password")
@api_admin
def reset_password(user_id: int):
    """Set a temporary password, returned once, and force a change at next login.

    The value comes back in the response and is stored nowhere else -- there is
    no second chance to read it, which is the same deal the HTML page offers.
    """
    db = get_db()
    target = user_repo.get(db, user_id)
    if not target:
        return error("No such user.", 404)
    temp = ((request.get_json(silent=True) or {}).get("password") or "").strip() \
        or user_repo.generate_password()
    problem = session_auth.password_problem(temp)
    if problem:
        return error(problem, 400)
    db.execute(sql(
        "UPDATE users SET password_hash=:h, must_change_password=true WHERE id=:id"),
        {"h": session_auth.hash_password(temp), "id": user_id})
    db.commit()
    log.info("Admin reset password for user id=%d", user_id)
    return jsonify({"username": target["username"], "password": temp})


# ── insights ──────────────────────────────────────────────────────────────────

@bp.get("/insights")
@api_admin
def insights_all():
    """Every panel in one call.

    Seven queries that are only ever read together, on a screen visited rarely.
    Seven round trips to draw one page would be the server's template layout
    leaking into the client again.
    """
    from app import pipeline
    from app.pipeline import SCORE_THRESHOLD

    db = get_db()
    threshold = float(get_setting(db, "score_threshold", str(SCORE_THRESHOLD))
                      or SCORE_THRESHOLD)
    return jsonify({
        "threshold": threshold,
        "histogram": [dict(r) for r in insights.score_histogram(db)],
        "agreement": insights.agreement(db, threshold),
        # None when nothing has been voted on: a suggestion from no data would
        # be a number with no meaning, and the client should say so instead.
        "suggestion": insights.suggest_threshold(db),
        "per_feed": [dict(r) for r in insights.per_feed(db)],
        "per_topic": [dict(r) for r in insights.per_topic(db)],
        "pipeline": dict(insights.pipeline_health(db)),
        "runs": [_run_row(r) for r in insights.recent_runs(db)],
        # A run reporting 0 scored in ~0s is a failing run, not an idle one.
        "llm_error": pipeline.last_llm_error(db),
    })


def _run_row(r) -> dict:
    return {
        "started_at": r["started_at"].isoformat() if r["started_at"] else None,
        "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
        "scored_n": r["scored_n"],
        "summarized_n": r["summarized_n"],
        "errors_n": r["errors_n"],
        "skipped": r["skipped"],
        "seconds": float(r["seconds"]) if r["seconds"] is not None else None,
    }


@bp.post("/insights/threshold")
@api_admin
def apply_threshold():
    """Adopt the swept threshold in one click."""
    db = get_db()
    raw = (request.get_json(silent=True) or {}).get("threshold")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return error("threshold must be a number.", 400)
    if not 0.0 <= value <= 1.0:
        return error("threshold must be between 0 and 1.", 400)
    set_setting(db, "score_threshold", str(value))
    db.commit()
    return jsonify({"threshold": value})


# ── Ollama call log ───────────────────────────────────────────────────────────

@bp.get("/ollama-log")
@api_admin
def ollama_log():
    db = get_db()
    only_failed = request.args.get("failed") == "1"
    return jsonify({
        "enabled": call_log.enabled(db),
        "keep": call_log.KEEP,
        "only_failed": only_failed,
        "summary": _summary(call_log.summary(db)),
        "calls": [_call_row(r) for r in call_log.recent(db, failures_only=only_failed)],
        # An empty log has two very different meanings: no calls are being made,
        # or none are needed. The queue is what tells them apart.
        "queue": dict(pipeline_status.counts(db)),
        # `pipeline_status.last_run` returns the whole run *row*, not a
        # timestamp. `_iso` only converts things that have `.isoformat()`, so a
        # dict fell straight through and the API sent an object where the
        # contract promised a string -- and the client called .slice() on it,
        # which threw and took the whole screen down. Only the finish time is
        # wanted here.
        "last_run": _iso((pipeline_status.last_run(db) or {}).get("finished_at")),
    })


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _summary(s: dict) -> dict:
    return {"total": s.get("total") or 0, "failed": s.get("failed") or 0,
            "newest": _iso(s.get("newest"))}


def _call_row(r) -> dict:
    return {
        "id": r["id"],
        "at": _iso(r["at"]),
        "action": r["action"],
        "model": r["model"],
        "endpoint": r["endpoint"],
        "ok": bool(r["ok"]),
        "status_code": r["status_code"],
        "duration_ms": r["duration_ms"],
        # Both sides, because the tail is where a reasoning model puts its
        # answer and the head is where a malformed prompt shows up.
        "request_preview": r["request_preview"],
        "response_preview": r["response_preview"],
        "error": r["error"],
    }


@bp.post("/ollama-log/toggle")
@api_admin
def ollama_log_toggle():
    db = get_db()
    on = bool((request.get_json(silent=True) or {}).get("enabled"))
    set_setting(db, call_log.SETTING, "1" if on else "")
    db.commit()
    return jsonify({"enabled": on})


@bp.post("/ollama-log/clear")
@api_admin
def ollama_log_clear():
    db = get_db()
    removed = call_log.clear(db)
    db.commit()
    return jsonify({"cleared": removed})

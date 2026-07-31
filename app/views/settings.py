"""The settings panels, plus the shared preference profile."""

import logging
from app import (auth, call_log, digest as digest_mod, export as export_mod,
                 extract, health, insights, pipeline_status, retention,
                 topics as topics_mod, user_topics)
from app import content_filter, ollama_client
from app import presenters
from app.db import get_db, get_setting, set_setting
from app.pipeline import DEFAULT_SCORING_MODEL, DEFAULT_SUMMARY_MODEL, ollama_base
from flask import (Blueprint, current_app, g, redirect, render_template,
                   request, Response, url_for)
from sqlalchemy import text as sql

from app.views import bp


log = logging.getLogger(__name__)


@bp.get("/settings")
@auth.admin_required
def settings():
    return render_template("settings.html")


def _ollama_form_state(db, **overrides) -> dict:
    """Values for _ollama_setting.html: saved settings, or the env default."""
    host = (get_setting(db, "ollama_host", "") or "").strip()
    port = (get_setting(db, "ollama_port", "") or "").strip()
    state = {
        "host": host,
        "port": port,
        "using_env": not (host and port),
        "env_base": ollama_client.OLLAMA_BASE,
        "active_base": ollama_base(db),
    }
    state.update(overrides)
    return state


@bp.get("/settings/ollama")
@auth.admin_required
def ollama_form():
    return render_template("_ollama_setting.html", **_ollama_form_state(get_db()))


@bp.post("/settings/ollama")
@auth.admin_required
def ollama_save():
    db = get_db()
    host = request.form.get("ollama_host", "").strip()
    port = request.form.get("ollama_port", "").strip()

    # Both blank is a deliberate "revert to the OLLAMA_HOST env var".
    if not host and not port:
        set_setting(db, "ollama_host", "")
        set_setting(db, "ollama_port", "")
        db.commit()
        return render_template(
            "_ollama_setting.html",
            **_ollama_form_state(db, saved=True,
                                 notice="Cleared — using the OLLAMA_HOST environment variable."),
        )

    try:
        base = ollama_client.compose_base_url(host, port)
    except ValueError as exc:
        return render_template(
            "_ollama_setting.html",
            **_ollama_form_state(db, host=host, port=port, error=str(exc)),
        )

    set_setting(db, "ollama_host", host)
    set_setting(db, "ollama_port", port)
    db.commit()
    log.info("Ollama endpoint set to %s", base)
    return render_template(
        "_ollama_setting.html",
        **_ollama_form_state(db, saved=True,
                             notice="Saved. Takes effect on the next pipeline run — no restart needed."),
    )


@bp.post("/settings/ollama/test")
@auth.admin_required
def ollama_test():
    """Probe the values currently in the form, without saving them."""
    db = get_db()
    host = request.form.get("ollama_host", "").strip()
    port = request.form.get("ollama_port", "").strip()

    if host or port:
        try:
            target = ollama_client.compose_base_url(host, port)
        except ValueError as exc:
            return render_template(
                "_ollama_setting.html",
                **_ollama_form_state(db, host=host, port=port, error=str(exc)),
            )
    else:
        target = ollama_client.OLLAMA_BASE

    ok, message, models = ollama_client.probe(target)
    return render_template(
        "_ollama_setting.html",
        **_ollama_form_state(db, host=host, port=port,
                             test_ok=ok, test_message=message, test_models=models),
    )


@bp.get("/settings/models")
@auth.admin_required
def models_form():
    """One model per job, with the choices Ollama actually has installed."""
    from app import llm_config
    db = get_db()
    installed = ollama_client.list_models(ollama_base(db))
    return render_template("_models.html", installed=installed,
                           rows=llm_config.current(db, installed))


@bp.post("/settings/models")
@auth.admin_required
def models_save():
    from app import llm_config
    db = get_db()
    action_id = request.form.get("action_id", "").strip()
    model = request.form.get("model", "").strip()
    try:
        llm_config.set_model(db, action_id, model)
    except ValueError as exc:
        return Response(str(exc), status=400)
    db.commit()
    installed = ollama_client.list_models(ollama_base(db))
    return render_template("_models.html", installed=installed,
                           rows=llm_config.current(db, installed), saved=True)


@bp.post("/settings/models/recommended")
@auth.admin_required
def models_use_recommended():
    """Set every job to the best installed model for it."""
    from app import llm_config
    db = get_db()
    installed = ollama_client.list_models(ollama_base(db))
    if not installed:
        return render_template("_models.html", installed=[],
                               rows=llm_config.current(db, []))
    changed = 0
    for action in llm_config.ACTIONS:
        suggested, _ = llm_config.recommend(action.id, installed)
        if suggested and llm_config.model_for(db, action.id) != suggested:
            llm_config.set_model(db, action.id, suggested)
            changed += 1
    db.commit()
    log.info("Applied recommended models to %d job(s)", changed)
    return render_template("_models.html", installed=installed,
                           rows=llm_config.current(db, installed), saved=True)


@bp.get("/settings/titles")
@auth.admin_required
def titles_form():
    db = get_db()
    return render_template("_titles_setting.html", enabled=presenters.declickbait(db))


@bp.post("/settings/titles")
@auth.admin_required
def titles_save():
    enabled = request.form.get("declickbait_enabled") == "1"
    db = get_db()
    set_setting(db, "declickbait_enabled", "1" if enabled else "")
    db.commit()
    return render_template("_titles_setting.html", enabled=enabled, saved=True)


@bp.get("/settings/content")
@auth.admin_required
def content_filter_form():
    db = get_db()
    return render_template(
        "_content_filter_setting.html",
        mode=presenters.content_filter_mode(db),
        llm_enabled=get_setting(db, "content_filter_llm", "") == "1",
    )


@bp.post("/settings/content")
@auth.admin_required
def content_filter_save():
    mode = request.form.get("content_filter_mode", "")
    if mode not in content_filter.MODES:
        return Response("invalid mode", status=400)
    llm = request.form.get("content_filter_llm") == "1"
    db = get_db()
    set_setting(db, "content_filter_mode", mode)
    set_setting(db, "content_filter_llm", "1" if llm else "")
    db.commit()
    return render_template(
        "_content_filter_setting.html", mode=mode, llm_enabled=llm, saved=True
    )


@bp.get("/settings/retention")
@auth.admin_required
def retention_form():
    db = get_db()
    return render_template(
        "_retention_setting.html",
        days=retention.retention_days(db),
        confirmed=retention.is_confirmed(db),
        preview=retention.preview(db),
        users=_users_for_cleanup(db),
    )


def _users_for_cleanup(db):
    from app.models import users as U
    from sqlalchemy import select as _select
    return db.execute(
        _select(U.c.id, U.c.username).order_by(U.c.id)
    ).mappings().all()


@bp.post("/settings/retention")
@auth.admin_required
def retention_save():
    raw = request.form.get("retention_days", "").strip()
    try:
        days = int(raw)
    except ValueError:
        return Response("days must be a whole number", status=400)
    if days < 0:
        return Response("days must be 0 or more", status=400)
    db = get_db()
    set_setting(db, retention.SETTING_DAYS, str(days))
    retention.set_confirmed(db, request.form.get("retention_confirmed") == "1")
    db.commit()
    return render_template(
        "_retention_setting.html",
        days=days,
        confirmed=retention.is_confirmed(db),
        preview=retention.preview(db),
        users=_users_for_cleanup(db),
        saved=True,
    )


@bp.post("/settings/retention/prune")
@auth.admin_required
def retention_prune_now():
    """Run the policy immediately. Requires the confirmation toggle."""
    db = get_db()
    if not retention.is_confirmed(db):
        return Response("confirm the retention policy first", status=400)
    n = retention.prune(db)
    db.commit()
    return render_template(
        "_retention_setting.html",
        days=retention.retention_days(db),
        confirmed=True,
        preview=retention.preview(db),
        users=_users_for_cleanup(db),
        pruned=n,
    )


@bp.post("/settings/retention/clear-read")
@auth.admin_required
def retention_clear_read():
    """Remove read articles from selected users' lists (or all users)."""
    db = get_db()
    if request.form.get("all_users") == "1":
        ids = [u["id"] for u in _users_for_cleanup(db)]
    else:
        ids = [int(v) for v in request.form.getlist("user_id") if v.isdigit()]
    if not ids:
        return Response("select at least one user", status=400)
    n = retention.clear_read(db, ids)
    db.commit()
    return render_template(
        "_retention_setting.html",
        days=retention.retention_days(db),
        confirmed=retention.is_confirmed(db),
        preview=retention.preview(db),
        users=_users_for_cleanup(db),
        cleared=n,
    )


@bp.get("/settings/notifications")
@auth.admin_required
def notifications_form():
    db = get_db()
    from app.pipeline import HIGH_SCORE_NOTIFY
    return render_template("_notifications_setting.html",
                           enabled=get_setting(db, "notify_high_score", "") == "1",
                           threshold=HIGH_SCORE_NOTIFY)


@bp.post("/settings/notifications")
@auth.admin_required
def notifications_save():
    db = get_db()
    enabled = request.form.get("notify_high_score") == "1"
    set_setting(db, "notify_high_score", "1" if enabled else "")
    db.commit()
    from app.pipeline import HIGH_SCORE_NOTIFY
    return render_template("_notifications_setting.html", enabled=enabled,
                           threshold=HIGH_SCORE_NOTIFY, saved=True)


@bp.get("/settings/topics")
@auth.admin_required
def topics_form():
    db = get_db()
    return render_template("_topics_setting.html", topics=topics_mod.counts(db))


@bp.post("/settings/topics")
@auth.admin_required
def topics_save():
    db = get_db()
    topic = request.form.get("topic", "").strip()
    action = request.form.get("action", "")
    try:
        if action == "clear":
            topics_mod.delete_rule(db, topic)
        elif action == "mute":
            topics_mod.set_rule(db, topic, muted=True)
        elif action == "renormalize":
            n = topics_mod.renormalize_all(db)
            db.commit()
            return render_template("_topics_setting.html",
                                   topics=topics_mod.counts(db),
                                   saved=True, renormalized=n)
        elif action in ("boost", "demote"):
            delta = 0.2 if action == "boost" else -0.2
            topics_mod.set_rule(db, topic, adjustment=delta)
        else:
            return Response("unknown action", status=400)
    except ValueError as exc:
        return render_template("_topics_setting.html", topics=topics_mod.counts(db),
                               error=str(exc))
    db.commit()
    return render_template("_topics_setting.html", topics=topics_mod.counts(db),
                           saved=True)


@bp.get("/settings/embeds")
@auth.admin_required
def embeds_form():
    db = get_db()
    enabled = get_setting(db, "embeds_enabled", "") == "1"
    return render_template("_embeds_setting.html", enabled=enabled)


@bp.post("/settings/embeds")
@auth.admin_required
def embeds_save():
    enabled = request.form.get("embeds_enabled") == "1"
    db = get_db()
    set_setting(db, "embeds_enabled", "1" if enabled else "")
    db.commit()
    return render_template("_embeds_setting.html", enabled=enabled, saved=True)

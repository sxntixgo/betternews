from unittest.mock import patch
def test_app_has_routes(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    for path in (
        "/",
        "/articles",
        "/feeds",
        "/feeds/opml",
        "/preferences",
        "/preferences/regenerate",
        "/status",
        "/settings",
        "/settings/models",
        "/settings/embeds",
        "/poll",
        "/count",
        "/manage-feeds",
        "/sidebar/feeds",
        "/rescore-hidden",
        "/dismiss-all",
        "/search",
        "/article/<int:article_id>/save",
        "/feeds/<int:feed_id>/pause",
        "/feeds/<int:feed_id>/resume",
        "/feeds/<int:feed_id>/threshold",
        "/feeds/<int:feed_id>/tags",
        "/article/<int:article_id>/dismiss",
    ):
        assert path in rules, f"missing route: {path}"


def test_scheduler_init_does_not_raise(app):
    from app.scheduler import init_scheduler
    sched = init_scheduler(app)
    assert sched is not None
    job_ids = {j.id for j in sched.get_jobs()}
    assert {"poll_feeds", "run_pipeline", "regen_prefs"}.issubset(job_ids)


def test_scheduler_error_listener(app, caplog):
    from app.scheduler import _on_job_error
    event = type("E", (), {"job_id": "x", "exception": RuntimeError("nope")})()
    _on_job_error(event)
    assert "raised" in caplog.text


# ── Scheduler placement ────────────────────────────────────────────────────────

def test_scheduler_does_not_run_in_web_by_default(monkeypatch, app):
    """One APScheduler per gunicorn worker would fire every job N times."""
    from app import _should_run_scheduler
    monkeypatch.delenv("RUN_SCHEDULER_IN_WEB", raising=False)
    assert _should_run_scheduler(app) is False


def test_scheduler_can_be_opted_back_into_web(monkeypatch, app):
    from app import _should_run_scheduler
    monkeypatch.setenv("RUN_SCHEDULER_IN_WEB", "1")
    app.debug = False
    assert _should_run_scheduler(app) is True


def test_worker_module_registers_every_job(app, monkeypatch):
    from app.scheduler import init_scheduler
    sched = init_scheduler(app)
    ids = {j.id for j in sched.get_jobs()}
    assert ids == {"poll_feeds", "run_pipeline", "regen_prefs", "retention"}


@patch("app.scheduler.init_scheduler")
def test_scheduler_starts_in_web_when_opted_in(mock_init, monkeypatch, database_url):
    """RUN_SCHEDULER_IN_WEB=1 restores the old single-worker behaviour."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("RUN_SCHEDULER_IN_WEB", "1")
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
    from app.db import dispose_engine
    dispose_engine()
    from app import create_app
    create_app()
    mock_init.return_value.start.assert_called_once()
    dispose_engine()


# ── Timestamp rendering ────────────────────────────────────────────────────────

def test_dt_filter_formats_datetimes():
    """Columns are TIMESTAMPTZ now; templates used to slice ISO strings."""
    from datetime import datetime, timezone
    from app import _fmt_dt
    assert _fmt_dt(datetime(2026, 7, 26, 5, 30, tzinfo=timezone.utc)) == "2026-07-26 05:30"


def test_dt_filter_tolerates_legacy_strings():
    from app import _fmt_dt
    assert _fmt_dt("2026-07-26T05:30:00Z") == "2026-07-26 05:30"


def test_dt_filter_handles_empty_and_odd_values():
    from app import _fmt_dt
    assert _fmt_dt(None) == ""
    assert _fmt_dt("") == ""
    assert _fmt_dt(12345) == "12345"


def test_feed_rows_render_with_real_timestamps(client, app):
    """Regression: the resume route 500'd because this branch slices a datetime."""
    from datetime import datetime, timezone
    from app.db import get_db_direct
    from sqlalchemy import text
    from tests.conftest import add_feed
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        db.execute(text("UPDATE feeds SET last_success_at=:t, last_polled_at=:t WHERE id=:i"),
                   {"t": datetime.now(timezone.utc), "i": fid})
        db.commit()
        db.close()
    r = client.post(f"/feeds/{fid}/resume")
    assert r.status_code == 200
    assert b"ok " in r.data

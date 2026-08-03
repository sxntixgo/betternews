from unittest.mock import patch


def test_the_server_renders_exactly_four_things(app):
    """The cut-over check, kept as a test rather than done once by eye.

    Everything a reader does is the SPA against `/api/v1`. Four HTML routes
    survive, each for a reason that is not "we did not get round to it":

      * /login, /register — a browser with no session needs somewhere to land
        that does not depend on the bundle having loaded. If the SPA were the
        only door, a broken build would lock everyone out with no way to tell
        whether the server was even up.
      * /logout — clears the cookie the SPA cannot touch, being HttpOnly.
      * /health — the container healthcheck curls it.

    An exact set, not a subset: a route creeping back in is how two UIs start
    disagreeing again, and that is the thing this phase existed to stop.
    """
    html = {r.rule for r in app.url_map.iter_rules()
            if not r.rule.startswith("/api/v1") and r.endpoint != "static"}
    assert html == {"/login", "/register", "/logout", "/health"}


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
    assert ids == {"poll_feeds", "run_pipeline", "regen_prefs", "retention",
                   "retry_paused"}


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


def test_no_test_file_defines_the_same_test_twice():
    """A redefined test silently replaces the first one.

    Python rebinds the name, pytest collects only the survivor, and the lost
    test takes its coverage with it -- which is exactly how it was noticed:
    one line of `app/api/feeds.py` went uncovered with no failing test to
    explain why. Nothing else in the suite would catch this.
    """
    import ast
    from pathlib import Path

    tests_dir = Path(__file__).resolve().parent
    clashes = {}
    for path in sorted(tests_dir.glob("test_*.py")):
        seen, dupes = set(), set()
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in seen:
                    dupes.add(node.name)
                seen.add(node.name)
        if dupes:
            clashes[path.name] = sorted(dupes)
    assert not clashes, f"redefined test functions: {clashes}"

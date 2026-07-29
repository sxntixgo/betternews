import json
import logging
import os
import sys

from flask import Flask


class JsonFormatter(logging.Formatter):
    """Single-line JSON log records, suitable for grep/jq/log-shippers."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> None:
    """Configure root logging once. LOG_FORMAT=json switches to structured output."""
    fmt = os.environ.get("LOG_FORMAT", "").lower()
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
    root = logging.getLogger()
    # Replace handlers idempotently — pytest re-imports the module.
    root.handlers = [handler]
    root.setLevel(logging.INFO)


_configure_logging()


def create_app() -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

    from app.db import close_db, init_db
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    app.add_template_filter(_fmt_dt, "dt")

    from app import auth, call_log
    auth.install(app)
    call_log.install(app)
    app.jinja_env.globals["current_user"] = auth.current_user
    app.jinja_env.globals["is_admin"] = auth.is_admin

    from app.views import bp
    from app.api import bp as api_bp
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
    from app import api as api_mod
    api_mod.install(app)

    # The scheduler normally runs as its own process (`python -m app.worker`),
    # because one APScheduler per gunicorn worker means every job fires N times.
    # RUN_SCHEDULER_IN_WEB=1 restores the old in-process behaviour for a
    # single-worker or dev setup.
    if _should_run_scheduler(app):
        from app.scheduler import init_scheduler
        scheduler = init_scheduler(app)
        scheduler.start()

    return app


def _fmt_dt(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Render a timestamp for display.

    Columns are TIMESTAMPTZ since the Postgres migration, so templates get
    datetimes where they used to get ISO strings. Tolerates both rather than
    letting a stray string slice raise in a template.
    """
    if not value:
        return ""
    if isinstance(value, str):
        return value[:16].replace("T", " ")
    try:
        return value.strftime(fmt)
    except AttributeError:
        return str(value)


def _should_run_scheduler(app: Flask) -> bool:
    if os.environ.get("RUN_SCHEDULER_IN_WEB", "") != "1":
        return False
    return os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug

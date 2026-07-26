"""Scheduler process.

    python -m app.worker

Runs polling, the pipeline and retention outside the web tier. APScheduler is
in-process, so hosting it inside gunicorn means one scheduler per worker and
every job firing N times. Giving it its own process lets the web tier scale
without duplicating work.

Jobs still take the Postgres advisory lock (`pipeline._try_advisory_lock`), so
even two schedulers cannot run the pipeline concurrently.
"""

import logging
import signal
import threading

from app import create_app
from app.scheduler import init_scheduler

log = logging.getLogger(__name__)


def main() -> int:
    app = create_app()
    scheduler = init_scheduler(app)
    scheduler.start()
    log.info("Scheduler started: %s", [j.id for j in scheduler.get_jobs()])

    stop = threading.Event()

    def _shutdown(signum, _frame):
        log.info("Signal %s — shutting scheduler down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        stop.wait()
    finally:
        scheduler.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

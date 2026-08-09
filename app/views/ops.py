"""The container healthcheck.

All that survives of the operational HTML. Pipeline control, insights and the
Ollama log are `/api/v1/{poll,rescore-hidden,insights,ollama-log}` now.

This one cannot follow them: Docker's healthcheck curls a URL, it does not hold
a session or parse a bearer token, so `/health` stays public and server-rendered
whatever else moves.
"""

import logging

from flask import jsonify

from app import health
from app.db import get_db

from app.views import bp

log = logging.getLogger(__name__)


@bp.get("/health")
def healthcheck():
    """Liveness *and* ingestion.

    Returning 200 while nothing has been ingested for weeks is how the June
    outage stayed invisible, so a stale feed set is a 503 rather than an "ok"
    that only means the process is running.
    """
    db = get_db()
    st = health.ingestion_status(db)
    body = {
        "status": "ok" if st["healthy"] else "degraded",
        "feeds_total": st["total"],
        "feeds_paused": st["paused"],
        # Not paused, but nothing has arrived from them inside the window --
        # the silent case, which `ingestion_stale` cannot show because that
        # keys on the newest success across all feeds. Counts only: /health is
        # public, so no feed titles or URLs go in this body.
        "feeds_stale": st["stale_feeds"],
        "last_success_at": st["last_success_at"].isoformat() if st["last_success_at"] else None,
        "ingestion_stale": st["stale"],
    }
    return jsonify(body), (200 if st["healthy"] else 503)

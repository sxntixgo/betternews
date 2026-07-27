"""Recording what was said to Ollama and what came back.

Off by default. When a run reports "0 scored" the log is the difference between
guessing and reading the server's own 404, so it is worth having available --
but it is a row per LLM call with a slice of the prompt, so it is not worth
having on all the time.

The web and worker are separate processes, so this goes to the database; an
in-memory buffer would be invisible to whichever process serves the page.
"""

import logging

from sqlalchemy import desc, func, select, text

from app.db import get_db_direct, get_setting
from app.models import ollama_calls as C

log = logging.getLogger(__name__)

SETTING = "ollama_call_log"
KEEP = 200          # bounded, or a busy pipeline fills the disk with prompts


def enabled(db) -> bool:
    return get_setting(db, SETTING, "") == "1"


def install(app) -> None:
    """Point ollama_client at the database.

    Each call opens its own connection: the caller may be mid-transaction, and a
    debug log must never roll back real work or be rolled back with it.
    """
    from app import ollama_client

    def sink(record: dict) -> None:
        db = get_db_direct()
        try:
            if not enabled(db):
                return
            db.execute(C.insert().values(**record))
            _trim(db)
            db.commit()
        except Exception as exc:
            log.debug("Could not write the Ollama call log: %s", exc)
            db.rollback()
        finally:
            db.close()

    ollama_client.set_call_sink(sink)


def _trim(db) -> None:
    db.execute(text("""
        DELETE FROM ollama_calls WHERE id IN (
            SELECT id FROM ollama_calls ORDER BY at DESC OFFSET :keep)
    """), {"keep": KEEP})


def recent(db, limit: int = 40, failures_only: bool = False):
    stmt = select(C).order_by(desc(C.c.at)).limit(limit)
    if failures_only:
        stmt = select(C).where(C.c.ok.is_(False)).order_by(desc(C.c.at)).limit(limit)
    return db.execute(stmt).mappings().all()


def summary(db) -> dict:
    row = db.execute(text("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE NOT ok) AS failed,
               MAX(at) AS newest
        FROM ollama_calls
    """)).mappings().first()
    return dict(row) if row else {"total": 0, "failed": 0, "newest": None}


def clear(db) -> int:
    return db.execute(C.delete()).rowcount

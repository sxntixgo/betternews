"""User accounts.

Phase 0 runs with a single implicit user so per-user state has an owner. Phase 1
adds registration, roles and sessions on top of the same rows — no second data
migration.
"""

from sqlalchemy import func, select

from app.models import users as U

# The account that owns all pre-accounts data. Phase 1's first registration
# claims this row rather than creating a parallel one.
BOOTSTRAP_USERNAME = "owner"


def get(db, user_id: int):
    return db.execute(select(U).where(U.c.id == user_id)).mappings().first()


def by_username(db, username: str):
    return db.execute(
        select(U).where(func.lower(U.c.username) == (username or "").strip().lower())
    ).mappings().first()


def count(db) -> int:
    return db.execute(select(func.count()).select_from(U)).scalar_one()


def ensure_bootstrap_user(db) -> int:
    """Return the id of the single implicit user, creating it if absent.

    Password hash is empty: this account cannot be logged into. Phase 1's
    registration sets a real hash on it for the first admin.
    """
    row = db.execute(select(U.c.id).order_by(U.c.id).limit(1)).first()
    if row:
        return row[0]
    return db.execute(
        U.insert().values(
            username=BOOTSTRAP_USERNAME, password_hash="", role="admin"
        ).returning(U.c.id)
    ).scalar_one()

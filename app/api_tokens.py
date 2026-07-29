"""Bearer tokens for clients that are not a browser.

Deliberately separate from `app/auth.py`, which owns sessions. One decorator
serving two auth models is how a session-fixation bug gets written: the browser
path has CSRF and redirect behaviour a token client must never inherit, and the
token path must never fall back to a cookie it happens to find.

The token is shown to the reader exactly once, at creation, and only its hash is
stored. Treat it as a password, because that is what it is.
"""

import hashlib
import logging
import secrets

from sqlalchemy import and_, func, select

from app.models import api_tokens as T

log = logging.getLogger(__name__)

# 32 bytes of urandom, URL-safe. Long enough that guessing is not a threat model.
TOKEN_BYTES = 32
PREFIX = "bn_"


def _hash(token: str) -> str:
    """SHA-256, not scrypt.

    Unlike a password this is high-entropy random, so there is nothing to
    brute-force and no need for a slow KDF -- and a slow one would run on every
    single API request.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def issue(db, user_id: int, name: str) -> str:
    """Create a token and return it. This is the only time it is ever visible."""
    token = PREFIX + secrets.token_urlsafe(TOKEN_BYTES)
    db.execute(T.insert().values(
        user_id=user_id, token_hash=_hash(token), name=(name or "device")[:60]))
    log.info("Issued API token %r for user %d", name, user_id)
    return token


def resolve(db, token: str) -> int | None:
    """The user this token belongs to, or None.

    Touches last_used_at so a reader can tell which device is still active and
    revoke the one they lost.
    """
    if not token:
        return None
    row = db.execute(
        select(T.c.id, T.c.user_id).where(and_(
            T.c.token_hash == _hash(token), T.c.revoked_at.is_(None)))
    ).first()
    if not row:
        return None
    db.execute(T.update().where(T.c.id == row[0]).values(last_used_at=func.now()))
    return row[1]


def revoke(db, user_id: int, token_id: int) -> bool:
    """Revoke one of *this* user's tokens.

    Scoped to the owner on purpose: the id comes from a form, and without the
    user_id clause anyone could revoke anyone's device.
    """
    result = db.execute(
        T.update()
        .where(and_(T.c.id == token_id, T.c.user_id == user_id,
                    T.c.revoked_at.is_(None)))
        .values(revoked_at=func.now())
    )
    return result.rowcount > 0


def for_user(db, user_id: int):
    """Live tokens, newest first. Never includes the token itself."""
    return db.execute(
        select(T.c.id, T.c.name, T.c.created_at, T.c.last_used_at)
        .where(and_(T.c.user_id == user_id, T.c.revoked_at.is_(None)))
        .order_by(T.c.created_at.desc())
    ).mappings().all()

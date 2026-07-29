"""The JSON API, version 1.

A separate blueprint, deliberately not content negotiation on the HTML routes.
`ops.py` varies one route on `Accept` and that is the pattern not to spread: a
single function serving two representations couples them, so every change to the
page risks the client, and the HTML path's session assumptions leak into the
JSON path.

Versioned from the first commit. `/api/v1` costs nothing today and cannot be
retrofitted once a phone in someone's pocket depends on it.

Everything a reader sees is serialized through `app.presenters`, never straight
from a row. That module exists precisely so the browser and the phone cannot
drift apart about which headline to show or which passages are padding.
"""

import logging
from functools import wraps

from flask import Blueprint, g, jsonify, request

from app import api_tokens
from app.db import get_db

log = logging.getLogger(__name__)

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def error(message: str, status: int):
    """Errors are JSON too, always.

    An HTML error page is the thing a native client cannot parse, and it will
    surface as a crash rather than a message.
    """
    return jsonify({"error": message, "status": status}), status


def api_auth(fn):
    """Require a bearer token. Never falls back to the session.

    A cookie that happens to ride along on an API request must not authenticate
    it: the browser sends cookies on cross-site requests, which is exactly the
    confused-deputy problem CSRF tokens exist for on the HTML side.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return error("Send an Authorization: Bearer <token> header.", 401)
        db = get_db()
        user_id = api_tokens.resolve(db, token.strip())
        if user_id is None:
            return error("That token is not valid, or has been revoked.", 401)
        db.commit()            # persist last_used_at even on a read-only call
        g.api_user_id = user_id
        return fn(*args, **kwargs)
    return wrapper


def current_api_user() -> int:
    return g.api_user_id


def install(app) -> None:
    """App-level error handlers for the API prefix.

    A blueprint's errorhandler only runs for errors raised *inside* one of its
    views. An unmatched URL never reaches a blueprint at all, so /api/v1/typo
    would answer with Flask's HTML 404 page -- the one thing a native client
    cannot parse. Same for a wrong method. Anything outside the prefix falls
    through to the normal HTML behaviour untouched.
    """
    @app.errorhandler(404)
    def _404(exc):
        if request.path.startswith(bp.url_prefix):
            return error("No such endpoint.", 404)
        return exc

    @app.errorhandler(405)
    def _405(exc):
        if request.path.startswith(bp.url_prefix):
            return error("That method is not allowed here.", 405)
        return exc


@bp.errorhandler(Exception)
def _unhandled(exc):
    # Without this a client gets Flask's HTML 500 page and reports a parse error
    # instead of the failure.
    log.exception("Unhandled API error: %s", exc)
    return error("Internal error.", 500)


# Registers the routes on `bp`. Must come last; see app/views/__init__.py for
# the same pattern and the same reason.
from app.api import articles, meta  # noqa: E402,F401

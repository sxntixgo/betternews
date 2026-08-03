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
# Imported under a different name on purpose. Binding `auth` here would put
# `app.auth` in this *package's* namespace, so `from app.api import auth` at the
# bottom would resolve to it instead of app/api/auth.py -- the submodule would
# never be imported and its routes would never register. The symptom is a 404
# from an endpoint whose file plainly exists.
from app import auth as session_auth
from app.db import get_db
from app.repo import users as user_repo

log = logging.getLogger(__name__)

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def error(message: str, status: int):
    """Errors are JSON too, always.

    An HTML error page is the thing a native client cannot parse, and it will
    surface as a crash rather than a message.
    """
    return jsonify({"error": message, "status": status}), status


def api_auth(fn):
    """Require a bearer token, or a browser session.

    Two mechanisms because there are two kinds of client. A phone cannot hold a
    cookie usefully, so it sends a bearer token. A browser should not hold a
    token at all -- anything JavaScript can read, injected JavaScript can steal
    -- so it sends an HttpOnly session cookie it never sees.

    This used to refuse the cookie, on the grounds that browsers attach cookies
    to cross-site requests and a cookie-authenticated API is a confused deputy.
    SameSite=Strict answers that better: the cookie is not sent cross-site at
    all. See auth.install().

    Bearer is checked first, so an explicit credential always wins over an
    ambient one -- a client that sends a token means to use *that* identity.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        db = get_db()

        if header:
            # A present-but-malformed Authorization header is an error, not a
            # cue to fall back to the cookie. A client that tried to
            # authenticate with a token and got it wrong should be told so,
            # rather than silently acting as whoever the session says.
            if scheme.lower() != "bearer" or not token:
                return error("Send an Authorization: Bearer <token> header.", 401)
            user_id = api_tokens.resolve(db, token.strip())
            if user_id is None:
                return error("That token is not valid, or has been revoked.", 401)
            db.commit()        # persist last_used_at even on a read-only call
        else:
            user_id = session_auth.current_user_id()
            if user_id is None:
                return error("Sign in, or send an Authorization: Bearer header.", 401)

        g.api_user_id = user_id
        return fn(*args, **kwargs)
    return wrapper


def api_admin(fn):
    """Require an admin, on top of being authenticated.

    @api_auth proves *who* is calling, not what they may do. Until now the API
    exposed nothing that needed the distinction; /poll and /rescore-hidden do --
    they are @admin_required on the HTML side, and a reader who could kick the
    pipeline from a phone would be a quiet privilege escalation.

    Mirrors auth.admin_required, but answers 403 as JSON rather than rendering
    a page a native client cannot read.
    """
    @wraps(fn)
    @api_auth
    def wrapper(*args, **kwargs):
        db = get_db()
        user = user_repo.get(db, current_api_user())
        if not user or user["role"] != "admin":
            return error("Admins only.", 403)
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
from app.api import (admin as admin_routes, articles,  # noqa: E402,F401
                     auth as auth_routes, feeds as feed_routes,
                     me as me_routes, meta,
                     settings as settings_routes)

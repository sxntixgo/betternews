"""The web views, as one blueprint across several modules.

One `Blueprint`, not one per module. Separate blueprints would rename every
endpoint (`main.login` -> `accounts.login`), churning the `url_for('main.…')`
call sites in the templates to buy nothing: the reason to split was file size,
and file size does not need a second Blueprint object.

A future JSON API *is* a separate blueprint, because there the URL prefix and
the endpoint namespace are both wanted. This one is not that case.
"""

import logging

from flask import Blueprint

from app import auth

log = logging.getLogger(__name__)

bp = Blueprint("main", __name__)


def current_user_id(db) -> int:
    """The acting user, from the session.

    Every route reaching this is behind `login_required`, so a missing session
    is a programming error rather than an anonymous visitor.

    Stays here rather than moving to `presenters`: it reads the session, which
    is exactly what that module must not do.
    """
    uid = auth.current_user_id()
    if uid is None:                                   # pragma: no cover - guarded
        raise RuntimeError("no authenticated user in request context")
    return uid


# Imported for their side effect: each module registers its routes on `bp`.
# Must come last, after `bp` and `current_user_id` exist -- this is the one
# place in the codebase where import order is load-bearing.
from app.views import (  # noqa: E402,F401
    accounts, admin, feeds, ops, reading, settings,
)

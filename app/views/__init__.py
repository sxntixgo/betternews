"""What is left of the server-rendered UI.

Everything a reader does now goes through `app/api/` and the SPA. Two things
still have to be HTML, and they are the only reason this package exists:

* **Sign-in and registration.** A browser arriving with no session needs
  somewhere to land that does not depend on the bundle having loaded. If the
  SPA were the only way in, a broken build would lock everyone out of their own
  reader with no way to tell whether the server was even up.
* **`/health`.** The container healthcheck curls it, so it must answer without
  a session and without JavaScript.

One `Blueprint` named `main` across both modules, kept from when there were
six: the endpoint names are what `url_for` and the tests refer to, and renaming
them to buy nothing is churn.
"""

import logging

from flask import Blueprint

log = logging.getLogger(__name__)

bp = Blueprint("main", __name__)


# Imported for their side effect: each module registers its routes on `bp`.
# Must come last, after `bp` exists -- this is the one place in the codebase
# where import order is load-bearing.
from app.views import accounts, ops  # noqa: E402,F401

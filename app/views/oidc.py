"""Single sign-on through an OpenID Connect provider (the home Authentik).

Authorization code flow with PKCE. Two routes, both under `/login` so the
reverse proxy already sends them here:

* `GET /login/sso` sends the browser to the provider.
* `GET /login/sso/callback` is where the provider sends it back.

**SSO signs in an existing account; it never creates one.** The provider's
`preferred_username` is matched case-insensitively against `users.username`.
Who may read is decided twice on purpose: by the account list here, and by the
group the provider binds to this application. A provider account with no news
account is turned away, so a mis-set group cannot quietly mint readers.

The ID token's signature is not checked, and does not need to be: the identity
comes from the userinfo endpoint, called with an access token this server just
received directly from the provider over TLS -- in exchange for a code that only
works with this app's client secret and the PKCE verifier. Nothing the browser
carried is trusted for *who*, only `state` for *which attempt*.

Configured by environment. With `OIDC_ISSUER` unset both routes answer 404 and
the sign-in page shows no button, so a deployment without a provider behaves
exactly as before:

    OIDC_ISSUER         https://sso.example/application/o/news/
    OIDC_CLIENT_ID      from the provider
    OIDC_CLIENT_SECRET  from the provider
    OIDC_REDIRECT_URI   https://news.example/login/sso/callback
    OIDC_NAME           button label, "Sign in with <name>" (default "SSO")
"""

import base64
import hashlib
import logging
import os
import secrets
from urllib.parse import urlencode

import httpx
from flask import abort, redirect, render_template, request, session

from app import auth
from app.db import get_db
from app.repo import users as user_repo
from app.views import bp

log = logging.getLogger(__name__)

_PENDING = "oidc_pending"      # session key: state + PKCE verifier of the attempt in flight
_TIMEOUT = 10
_discovery: dict[str, dict] = {}


def configured() -> bool:
    return bool(os.environ.get("OIDC_ISSUER"))


def _issuer() -> str:
    return os.environ["OIDC_ISSUER"].rstrip("/") + "/"


def _provider() -> dict:
    """The provider's endpoints, fetched once per process."""
    issuer = _issuer()
    if issuer not in _discovery:
        r = httpx.get(issuer + ".well-known/openid-configuration", timeout=_TIMEOUT)
        r.raise_for_status()
        _discovery[issuer] = r.json()
    return _discovery[issuer]


def button_name() -> str:
    return os.environ.get("OIDC_NAME") or "SSO"


@bp.app_context_processor
def _sso_button():
    return {"sso_name": button_name() if configured() else None}


def _fail(message: str, code: int):
    return render_template("login.html", error=message, first_run=False), code


@bp.get("/login/sso")
def sso_start():
    if not configured():
        abort(404)
    try:
        endpoint = _provider()["authorization_endpoint"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("SSO provider discovery failed: %s", exc)
        return _fail("Single sign-on is unavailable right now. Sign in with your password.", 502)

    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(24)
    session[_PENDING] = {"state": state, "verifier": verifier}
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urlencode({
        "response_type": "code",
        "client_id": os.environ["OIDC_CLIENT_ID"],
        "redirect_uri": os.environ["OIDC_REDIRECT_URI"],
        "scope": "openid profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return redirect(f"{endpoint}?{query}")


@bp.get("/login/sso/callback")
def sso_callback():
    if not configured():
        abort(404)
    # Popped, not read: a state is good for one attempt, success or not.
    pending = session.pop(_PENDING, None)

    if request.args.get("error"):
        return _fail("Single sign-on was cancelled or refused.", 403)
    code = request.args.get("code", "")
    if (not pending or not code
            or not secrets.compare_digest(request.args.get("state", ""), pending["state"])):
        return _fail("That sign-in attempt expired. Try again.", 400)

    try:
        provider = _provider()
        token = httpx.post(
            provider["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": os.environ["OIDC_REDIRECT_URI"],
                "code_verifier": pending["verifier"],
            },
            auth=(os.environ["OIDC_CLIENT_ID"], os.environ["OIDC_CLIENT_SECRET"]),
            timeout=_TIMEOUT,
        )
        token.raise_for_status()
        info = httpx.get(
            provider["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            timeout=_TIMEOUT,
        )
        info.raise_for_status()
        username = (info.json().get("preferred_username") or "").strip()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("SSO code exchange failed: %s", exc)
        return _fail("Single sign-on failed. Try again, or sign in with your password.", 502)

    db = get_db()
    user = user_repo.by_username(db, username) if username else None
    if not user:
        log.info("SSO sign-in refused: no account named %r", username)
        return _fail("There is no news account for that sign-in.", 403)

    auth.clear_failures(db, user["username"])
    auth.login_user(db, user["id"])
    db.commit()
    log.info("SSO sign-in for %r", user["username"])
    return redirect("/")

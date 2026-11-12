"""Single sign-on (app/views/oidc.py).

The provider is faked at the HTTP layer: `httpx.get` / `httpx.post` as the module
sees them. What matters is what this server sends and what it believes, not
what a real provider would do.
"""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

ISSUER = "https://sso.test/application/o/news/"
PROVIDER = {
    "authorization_endpoint": "https://sso.test/application/o/authorize/",
    "token_endpoint": "https://sso.test/application/o/token/",
    "userinfo_endpoint": "https://sso.test/application/o/userinfo/",
}


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "bad", request=httpx.Request("GET", "https://sso.test"), response=None)


@pytest.fixture
def sso(monkeypatch):
    """Configure SSO and fake the provider. Returns the recorded calls and knobs."""
    from app.views import oidc
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", "news-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "news-secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://news.test/login/sso/callback")
    monkeypatch.delenv("OIDC_NAME", raising=False)
    oidc._discovery.clear()

    state = {"username": "alice", "token_status": 200, "calls": []}

    def fake_get(url, **kw):
        state["calls"].append(("GET", url, kw))
        if url == ISSUER + ".well-known/openid-configuration":
            return _Resp(200, PROVIDER)
        if url == PROVIDER["userinfo_endpoint"]:
            return _Resp(200, {"preferred_username": state["username"], "sub": "abc"})
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, **kw):
        state["calls"].append(("POST", url, kw))
        assert url == PROVIDER["token_endpoint"]
        return _Resp(state["token_status"], {"access_token": "at-1", "token_type": "Bearer"})

    monkeypatch.setattr(oidc.httpx, "get", fake_get)
    monkeypatch.setattr(oidc.httpx, "post", fake_post)
    yield state
    oidc._discovery.clear()


def _user(app, username="alice"):
    from app import auth
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        uid = auth.register_user(db, username, "a-long-password")
        db.commit()
        db.close()
    return uid


def _start(client):
    """Begin a sign-in; return the parsed authorize query."""
    r = client.get("/login/sso")
    assert r.status_code == 302
    url = urlparse(r.headers["Location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == PROVIDER["authorization_endpoint"]
    return {k: v[0] for k, v in parse_qs(url.query).items()}


def _user_count(app):
    from app.db import get_db_direct
    from app.repo import users as user_repo
    with app.app_context():
        db = get_db_direct()
        n = user_repo.count(db)
        db.close()
    return n


# ── off by default ─────────────────────────────────────────────────────────────

def test_without_an_issuer_the_routes_are_404_and_there_is_no_button(anon_client, monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    assert anon_client.get("/login/sso").status_code == 404
    assert anon_client.get("/login/sso/callback?code=x&state=y").status_code == 404
    assert b"Sign in with" not in anon_client.get("/login").data


# ── start ──────────────────────────────────────────────────────────────────────

def test_the_login_page_offers_sso_when_configured(anon_client, sso, monkeypatch):
    assert b"Sign in with SSO" in anon_client.get("/login").data
    monkeypatch.setenv("OIDC_NAME", "Authentik")
    assert b"Sign in with Authentik" in anon_client.get("/login").data


def test_start_sends_the_browser_to_the_provider_with_state_and_pkce(anon_client, sso):
    q = _start(anon_client)
    assert q["response_type"] == "code"
    assert q["client_id"] == "news-client"
    assert q["redirect_uri"] == "https://news.test/login/sso/callback"
    assert q["code_challenge_method"] == "S256"
    with anon_client.session_transaction() as s:
        pending = s["oidc_pending"]
    assert q["state"] == pending["state"]
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(pending["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == expected
    # The verifier itself never goes to the browser's address bar.
    assert pending["verifier"] not in str(q)


# ── callback ───────────────────────────────────────────────────────────────────

def test_callback_signs_in_the_matching_account(app, anon_client, sso):
    uid = _user(app, "Alice")           # matched case-insensitively
    q = _start(anon_client)
    r = anon_client.get(f"/login/sso/callback?code=c-1&state={q['state']}")
    assert r.status_code == 302 and r.headers["Location"] == "/"
    with anon_client.session_transaction() as s:
        assert s["user_id"] == uid
        assert "oidc_pending" not in s

    post = [c for c in sso["calls"] if c[0] == "POST"][0][2]
    assert post["auth"] == ("news-client", "news-secret")
    assert post["data"]["code"] == "c-1"
    assert post["data"]["grant_type"] == "authorization_code"
    assert post["data"]["code_verifier"]
    userinfo = [c for c in sso["calls"] if c[1] == PROVIDER["userinfo_endpoint"]][0][2]
    assert userinfo["headers"]["Authorization"] == "Bearer at-1"


def test_callback_never_creates_an_account(app, anon_client, sso):
    _user(app, "someone-else")
    before = _user_count(app)
    q = _start(anon_client)
    r = anon_client.get(f"/login/sso/callback?code=c-1&state={q['state']}")
    assert r.status_code == 403
    assert b"no news account" in r.data
    assert _user_count(app) == before
    with anon_client.session_transaction() as s:
        assert "user_id" not in s


@pytest.mark.parametrize("bad_state", ["", "forged"])
def test_callback_rejects_a_state_it_did_not_issue(app, anon_client, sso, bad_state):
    _user(app)
    _start(anon_client)
    r = anon_client.get(f"/login/sso/callback?code=c-1&state={bad_state}")
    assert r.status_code == 400
    assert not [c for c in sso["calls"] if c[0] == "POST"]    # no code exchange attempted
    with anon_client.session_transaction() as s:
        assert "user_id" not in s


def test_a_state_works_once(app, anon_client, sso):
    _user(app)
    q = _start(anon_client)
    assert anon_client.get(f"/login/sso/callback?code=c-1&state={q['state']}").status_code == 302
    anon_client.get("/logout")
    assert anon_client.get(f"/login/sso/callback?code=c-1&state={q['state']}").status_code == 400


def test_callback_without_a_started_attempt_is_rejected(app, anon_client, sso):
    _user(app)
    assert anon_client.get("/login/sso/callback?code=c-1&state=s").status_code == 400


def test_provider_refusal_is_reported_not_signed_in(app, anon_client, sso):
    _user(app)
    q = _start(anon_client)
    r = anon_client.get(f"/login/sso/callback?error=access_denied&state={q['state']}")
    assert r.status_code == 403
    with anon_client.session_transaction() as s:
        assert "user_id" not in s


def test_a_failed_code_exchange_is_a_502_not_a_sign_in(app, anon_client, sso):
    _user(app)
    sso["token_status"] = 400
    q = _start(anon_client)
    r = anon_client.get(f"/login/sso/callback?code=c-1&state={q['state']}")
    assert r.status_code == 502
    with anon_client.session_transaction() as s:
        assert "user_id" not in s


# ── what the SPA asks ──────────────────────────────────────────────────────────

def test_the_spa_is_told_whether_sso_is_offered(anon_client, monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    r = anon_client.get("/api/v1/auth/sso")
    assert r.status_code == 200
    assert r.get_json() == {"enabled": False, "name": None, "url": None}


def test_the_spa_gets_the_button_label_and_where_it_goes(anon_client, sso, monkeypatch):
    monkeypatch.setenv("OIDC_NAME", "Authentik")
    r = anon_client.get("/api/v1/auth/sso")   # signed out: the sign-in screen asks before anyone has a session
    assert r.status_code == 200
    assert r.get_json() == {"enabled": True, "name": "Authentik", "url": "/login/sso"}

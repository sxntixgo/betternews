"""The JSON API and its bearer tokens.

The rule this file exists to enforce: a token authenticates the API, a session
does not, and the two never substitute for one another.
"""

import pytest

from app import api_tokens
from tests.conftest import add_article, add_feed

API = "/api/v1"


@pytest.fixture
def token(app):
    from app.db import get_db_direct
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        uid = ensure_bootstrap_user(db)
        value = api_tokens.issue(db, uid, "test device")
        db.commit()
        db.close()
    return value


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── the auth boundary ─────────────────────────────────────────────────────────

EVERY_ENDPOINT = [
    ("get", f"{API}/articles"), ("get", f"{API}/articles/1"),
    ("post", f"{API}/articles/1/save"), ("post", f"{API}/articles/1/dismiss"),
    ("post", f"{API}/articles/1/read"), ("post", f"{API}/articles/1/vote"),
    ("get", f"{API}/feeds"), ("get", f"{API}/topics"),
    ("post", f"{API}/topics/space/stance"), ("get", f"{API}/digest"),
    ("get", f"{API}/me"),
]


@pytest.fixture
def anon(app):
    """A client with no session at all.

    `client` is signed in, so using it for these made them pass for the wrong
    reason: the session satisfied the app-wide guard and only then did the
    missing bearer token produce a 401. A real client has no cookie, and the
    guard was answering it with a 302 to /login.
    """
    return app.test_client()


@pytest.mark.parametrize("method,path", EVERY_ENDPOINT)
def test_every_endpoint_refuses_an_anonymous_request(anon, method, path):
    r = getattr(anon, method)(path)
    assert r.status_code == 401, f"got {r.status_code}; a redirect means the " \
                                 f"session guard is intercepting the API"
    assert r.is_json, "a native client cannot parse an HTML error page"


def test_a_token_works_without_any_session(anon, token):
    """The end-to-end case the signed-in test client could never exercise."""
    r = anon.get(f"{API}/me", headers=auth(token))
    assert r.status_code == 200, "a bearer token must be sufficient on its own"
    assert r.get_json()["username"]


@pytest.mark.parametrize("method,path", EVERY_ENDPOINT)
def test_a_browser_session_now_authenticates_the_api(client, app, method, path):
    """This assertion is the inverse of what it used to be, deliberately.

    The API was bearer-only so that a cookie could never authenticate a
    cross-site request. SameSite=Strict answers that better -- the browser does
    not send the cookie cross-site at all -- and it lets the SPA sign in with a
    password and hold no credential in JavaScript. `client` is session-signed-in,
    so every endpoint must now accept it.
    """
    r = getattr(client, method)(path)
    assert r.status_code != 401, f"{method} {path} rejected a valid session"


def test_a_revoked_token_stops_working(client, app, token):
    from app.db import get_db_direct
    assert client.get(f"{API}/me", headers=auth(token)).status_code == 200
    with app.app_context():
        db = get_db_direct()
        uid = client.application  # noqa: F841 - readability only
        from app.repo.users import ensure_bootstrap_user
        user_id = ensure_bootstrap_user(db)
        row = api_tokens.for_user(db, user_id)[0]
        api_tokens.revoke(db, user_id, row["id"])
        db.commit()
        db.close()
    r = client.get(f"{API}/me", headers=auth(token))
    assert r.status_code == 401
    assert "revoked" in r.get_json()["error"]


def test_a_garbage_token_is_rejected(client, token):
    assert client.get(f"{API}/me", headers=auth("bn_nonsense")).status_code == 401
    assert client.get(f"{API}/me", headers={"Authorization": token}).status_code == 401


def test_the_token_is_only_ever_stored_hashed(app):
    from app.db import get_db_direct
    from sqlalchemy import text
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        uid = ensure_bootstrap_user(db)
        value = api_tokens.issue(db, uid, "phone")
        db.commit()
        stored = db.execute(text("SELECT token_hash FROM api_tokens")).scalar()
        db.close()
    assert value not in stored
    assert len(stored) == 64, "sha256 hex"


def test_one_users_token_cannot_revoke_anothers(app):
    from app.db import get_db_direct
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        owner = ensure_bootstrap_user(db)
        api_tokens.issue(db, owner, "owners phone")
        db.commit()
        theirs = api_tokens.for_user(db, owner)[0]["id"]
        assert api_tokens.revoke(db, owner + 999, theirs) is False
        assert len(api_tokens.for_user(db, owner)) == 1
        db.close()


# ── reading ───────────────────────────────────────────────────────────────────

def test_listing_articles(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        add_article(db, fid, seq=1, guid="a", title="First", topics=["space"])
        db.close()
    body = client.get(f"{API}/articles", headers=auth(token)).get_json()
    assert [a["title"] for a in body["articles"]] == ["First"]
    got = body["articles"][0]
    assert got["topics"] == ["space"]
    assert got["state"] == {"read": False, "saved": False, "dismissed": False,
                            "opinion": None}
    assert body["next_offset"] is None, "one page, so no next"


def test_the_api_shows_the_same_headline_as_the_browser(client, app, token):
    """The reason serialization goes through presenters: with de-clickbait on,
    both clients must resolve the title identically."""
    from app.db import get_db_direct
    from app.db import set_setting
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        add_article(db, fid, seq=1, guid="c", title="The real headline",
                    clean_title="Rewritten", title_was_clickbait=True)
        set_setting(db, "declickbait_enabled", "1")
        db.commit()
        db.close()
    got = client.get(f"{API}/articles", headers=auth(token)).get_json()["articles"][0]
    assert got["title"] == "Rewritten"
    assert got["original_title"] == "The real headline"
    assert b"Rewritten" in client.get("/articles").data


def test_voting_through_the_api(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), seq=1, guid="v")
        db.close()
    r = client.post(f"{API}/articles/{aid}/vote", json={"value": 1},
                    headers=auth(token))
    assert r.get_json()["state"]["opinion"] == "liked"


def test_a_bad_vote_value_is_rejected(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), seq=1, guid="v2")
        db.close()
    r = client.post(f"{API}/articles/{aid}/vote", json={"value": 7},
                    headers=auth(token))
    assert r.status_code == 400


def test_saving_and_dismissing(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), seq=1, guid="s")
        db.close()
    assert client.post(f"{API}/articles/{aid}/save",
                       headers=auth(token)).get_json()["state"]["saved"] is True
    assert client.post(f"{API}/articles/{aid}/dismiss",
                       headers=auth(token)).get_json()["state"]["dismissed"] is True


def test_reading_one_article_returns_blocks_and_marks_it_read(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), seq=1, guid="r",
                          full_text="First para.\nSecond para.")
        db.close()
    body = client.get(f"{API}/articles/{aid}", headers=auth(token)).get_json()
    assert body["blocks"], "the client must not have to parse the body itself"
    # Reflects the read this very call performed. Returning false here made
    # every client patch the value it had just been handed.
    assert body["state"]["read"] is True


def test_a_missing_article_is_json_not_html(client, token):
    r = client.get(f"{API}/articles/999999", headers=auth(token))
    assert r.status_code == 404
    assert r.is_json


def test_an_unknown_endpoint_is_json(client, token):
    r = client.get(f"{API}/nope", headers=auth(token))
    assert r.status_code == 404
    assert r.is_json


def test_feeds_and_me(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db, title="A feed"), seq=1, guid="f")
        db.close()
    feeds = client.get(f"{API}/feeds", headers=auth(token)).get_json()
    assert feeds["feeds"][0]["title"] == "A feed"
    assert feeds["unread"] == 1
    me = client.get(f"{API}/me", headers=auth(token)).get_json()
    assert me["username"] and me["role"] in ("admin", "user")


def test_paging_through_the_api_never_repeats(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        for i in range(25):
            add_article(db, fid, seq=i, guid=f"p{i}", title=f"Item {i}")
        db.close()
    seen, offset = [], 0
    while True:
        body = client.get(f"{API}/articles?limit=10&offset={offset}",
                          headers=auth(token)).get_json()
        seen += [a["id"] for a in body["articles"]]
        if body["next_offset"] is None:
            break
        offset = body["next_offset"]
    assert len(seen) == len(set(seen)) == 25


def test_limit_is_clamped(client, app, token):
    r = client.get(f"{API}/articles?limit=99999", headers=auth(token))
    assert r.status_code == 200
    r = client.get(f"{API}/articles?limit=notanumber", headers=auth(token))
    assert r.status_code == 200


# ── the remaining paths ───────────────────────────────────────────────────────

def test_a_wrong_method_is_json(client, token):
    r = client.post(f"{API}/feeds", headers=auth(token))
    assert r.status_code == 405
    assert r.is_json


def test_a_404_outside_the_api_is_still_html(client):
    """The handler must not hijack the whole app."""
    r = client.get("/definitely-not-a-page")
    assert r.status_code == 404
    assert not r.is_json


def test_an_unhandled_error_is_json_not_a_stack_page(client, app, token, monkeypatch):
    from app.repo import articles as art_repo
    monkeypatch.setattr(art_repo, "sidebar_counts",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.get(f"{API}/feeds", headers=auth(token))
    assert r.status_code == 500
    assert r.is_json and r.get_json()["error"] == "Internal error."


def test_resolve_ignores_an_empty_token(app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        assert api_tokens.resolve(db, "") is None
        db.close()


def test_offset_and_limit_survive_nonsense(client, token):
    assert client.get(f"{API}/articles?offset=-5", headers=auth(token)).status_code == 200
    assert client.get(f"{API}/articles?offset=abc", headers=auth(token)).status_code == 200


def test_topics_round_trip(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), seq=1, guid="t", topics=["space"])
        db.close()
    assert client.get(f"{API}/topics", headers=auth(token)).status_code == 200
    r = client.post(f"{API}/topics/space/stance", json={"stance": "more"},
                    headers=auth(token))
    assert r.get_json() == {"topic": "space", "stance": "more"}
    listed = client.get(f"{API}/topics", headers=auth(token)).get_json()["topics"]
    assert any(t["topic"] == "space" and t["stance"] == "more" for t in listed)


def test_a_bad_stance_is_rejected(client, token):
    r = client.post(f"{API}/topics/space/stance", json={"stance": "sideways"},
                    headers=auth(token))
    assert r.status_code == 400
    assert r.is_json


def test_the_digest_endpoint(client, app, token):
    from unittest.mock import patch
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        for i in range(6):
            add_article(db, fid, seq=i, guid=f"d{i}")
        db.close()
    with patch("app.ollama_client.generate", return_value="**Theme**\nA briefing."):
        body = client.get(f"{API}/digest", headers=auth(token)).get_json()
    assert body["body"].startswith("**Theme**")
    assert body["article_count"] >= 6
    assert body["cached"] is False


def test_a_405_outside_the_api_is_still_html(client):
    """The API handler must not hijack method errors on the HTML side."""
    r = client.post("/insights")
    assert r.status_code == 405
    assert not r.is_json


def test_acting_on_a_missing_article_is_json(client, token):
    for path in ("save", "dismiss", "read", "vote"):
        r = client.post(f"{API}/articles/999999/{path}",
                        json={"value": 1}, headers=auth(token))
        assert r.status_code == 404, path
        assert r.is_json, path


def test_marking_read_explicitly(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), seq=1, guid="mr")
        db.close()
    r = client.post(f"{API}/articles/{aid}/read", headers=auth(token))
    assert r.get_json()["state"]["read"] is True


# ── signing in with a password ────────────────────────────────────────────────

LOGIN = f"{API}/auth/login"

CREDS = {"username": "reader", "password": "correct horse battery staple"}


@pytest.fixture
def registered(app):
    """A user with a real password hash.

    conftest's add_user stores password_hash="x" and its client fakes the
    session, so neither can exercise a password check.
    """
    from app import auth as auth_mod
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        uid = auth_mod.register_user(db, CREDS["username"], CREDS["password"])
        db.commit()
        db.close()
    return uid


def test_login_sets_a_cookie_and_returns_no_credential(anon, registered, app):
    """The point of the whole phase: the browser never handles a token."""
    r = anon.post(LOGIN, json=CREDS)
    assert r.status_code == 200
    body = r.get_json()
    assert body["username"] == CREDS["username"]
    # Nothing token-shaped anywhere in the response.
    assert "token" not in str(body).lower()
    # And the session now works with no Authorization header at all.
    assert anon.get(f"{API}/me").status_code == 200


def test_the_session_cookie_is_httponly_and_strict(anon, registered, app):
    r = anon.post(LOGIN, json=CREDS)
    cookie = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie, "injected script must not be able to read it"
    assert "SameSite=Strict" in cookie, "this is what replaces bearer-only for CSRF"


def test_a_wrong_password_is_refused_without_saying_why(anon, registered):
    r = anon.post(LOGIN, json={**CREDS, "password": "wrong"})
    assert r.status_code == 401
    # Must not distinguish a bad password from a missing account, or the form
    # becomes a way to enumerate usernames.
    other = anon.post(LOGIN, json={"username": "nobody", "password": "wrong"})
    assert other.status_code == 401
    assert r.get_json()["error"] == other.get_json()["error"]


def test_repeated_failures_lock_the_account_out(anon, registered, app):
    """The HTML login already does this. A second password path that forgets it
    is how brute-force protection quietly stops applying."""
    codes = [anon.post(LOGIN, json={**CREDS, "password": "no"}).status_code
             for _ in range(8)]
    assert 429 in codes, f"never locked out: {codes}"


def test_logging_out_ends_the_session(anon, registered, app):
    anon.post(LOGIN, json=CREDS)
    assert anon.get(f"{API}/me").status_code == 200
    assert anon.post(f"{API}/auth/logout").status_code == 200
    assert anon.get(f"{API}/me").status_code == 401


def test_login_is_the_only_endpoint_reachable_anonymously(anon):
    assert anon.post(LOGIN, json={}).status_code in (400, 401)
    for method, path in EVERY_ENDPOINT:
        assert getattr(anon, method)(path).status_code == 401, path


def test_a_bearer_token_still_works_with_no_cookie(anon, token):
    """The phone cannot use a cookie, so this path must not regress."""
    assert anon.get(f"{API}/me", headers=auth(token)).status_code == 200


def test_login_reports_a_forced_password_change(anon, registered, app):
    """After an admin reset the HTML UI blocks everything until the password is
    changed; the API cannot show that form, so it reports the flag instead and
    the client decides. Phase 5 adds the endpoint to act on it."""
    from app.db import get_db_direct
    from sqlalchemy import text
    with app.app_context():
        db = get_db_direct()
        db.execute(text("UPDATE users SET must_change_password = true"))
        db.commit()
        db.close()
    body = anon.post(LOGIN, json=CREDS).get_json()
    assert body["must_change_password"] is True

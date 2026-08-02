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


# ── phase 2: the rest of what a reading client needs ──────────────────────────

ADMIN_ENDPOINTS = [("post", f"{API}/poll"), ("post", f"{API}/rescore-hidden")]


def test_search_finds_by_title(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        add_article(db, fid, seq=1, guid="s1", title="Quantum computing leaps")
        add_article(db, fid, seq=2, guid="s2", title="Football results")
        db.close()
    body = client.get(f"{API}/search?q=quantum", headers=auth(token)).get_json()
    assert [a["title"] for a in body["articles"]] == ["Quantum computing leaps"]


def test_search_survives_a_malformed_query(client, token):
    """websearch_to_tsquery does not raise where FTS5 MATCH would."""
    r = client.get(f"{API}/search?q=%22unclosed", headers=auth(token))
    assert r.status_code == 200


def test_search_needs_a_query(client, token):
    assert client.get(f"{API}/search", headers=auth(token)).status_code == 400


def test_dismiss_all_takes_the_same_filters_as_the_list(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        add_article(db, fid, seq=1, guid="d1", title="Spacey", topics=["space"])
        add_article(db, fid, seq=2, guid="d2", title="Other", topics=["economy"])
        db.close()
    n = client.post(f"{API}/articles/dismiss-all?topic=space",
                    headers=auth(token)).get_json()["dismissed"]
    assert n == 1
    got = {a["title"]: a["state"]["dismissed"]
           for a in client.get(f"{API}/articles", headers=auth(token)).get_json()["articles"]}
    assert got == {"Spacey": True, "Other": False}


def test_status_reports_the_pipeline_stamp(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), seq=1, guid="st")
        db.close()
    body = client.get(f"{API}/status", headers=auth(token)).get_json()
    # The SPA polls this and refetches when last_pipeline_run_at advances.
    assert set(body) >= {"last_pipeline_run_at", "last_poll_at", "feed_count",
                         "article_counts", "high_score"}
    assert body["feed_count"] == 1


def test_digest_dismiss_clears_the_cached_briefing(client, app, token):
    from unittest.mock import patch
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        for i in range(6):
            add_article(db, fid, seq=i, guid=f"dd{i}")
        db.close()
    with patch("app.ollama_client.generate", return_value="**Theme**\nBrief."):
        assert client.get(f"{API}/digest", headers=auth(token)).get_json()["cached"] is False
        assert client.get(f"{API}/digest", headers=auth(token)).get_json()["cached"] is True
        assert client.post(f"{API}/digest/dismiss", headers=auth(token)).status_code == 200
        assert client.get(f"{API}/digest", headers=auth(token)).get_json()["cached"] is False


def test_export_returns_a_zip(client, app, token):
    from app.db import get_db_direct
    from app.repo.articles import toggle_saved
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), seq=1, guid="ex", title="Kept")
        toggle_saved(db, ensure_bootstrap_user(db), aid)
        db.commit()
        db.close()
    r = client.get(f"{API}/export?scope=saved", headers=auth(token))
    assert r.status_code == 200
    assert r.mimetype == "application/zip"
    # A client cannot use <a download> with a bearer header, so it fetches the
    # body and builds a Blob -- the filename has to travel in the header.
    assert "attachment" in r.headers["Content-Disposition"]
    import io, zipfile
    names = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert any(n.endswith(".md") for n in names)


def test_export_rejects_an_unknown_scope(client, token):
    assert client.get(f"{API}/export?scope=everything",
                      headers=auth(token)).status_code == 400


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_only_endpoints_refuse_a_plain_user(app, method, path):
    """The API had no role check at all -- @api_auth proves who, not what.
    Without this, any reader could kick the pipeline."""
    from app.db import get_db_direct
    from tests.conftest import add_user
    from app import api_tokens as tok
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="plain", role="user")
        value = tok.issue(db, uid, "plain device")
        db.commit()
        db.close()
    c = app.test_client()
    r = getattr(c, method)(path, headers={"Authorization": f"Bearer {value}"})
    assert r.status_code == 403, path
    assert r.is_json


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_only_endpoints_accept_an_admin(client, token, method, path):
    from unittest.mock import patch
    with patch("threading.Thread"):
        assert getattr(client, method)(path, headers=auth(token)).status_code == 200


def _run_threads_inline():
    """Make Thread.start() call the target directly, so the body is covered."""
    from unittest.mock import MagicMock, patch
    ctx = patch("threading.Thread")
    mock = ctx.__enter__()

    def fake(target, daemon=False):
        t = MagicMock()
        t.start = lambda: target()
        return t

    mock.side_effect = fake
    return ctx


def test_poll_runs_the_pipeline_in_its_thread(client, app, token):
    from unittest.mock import patch
    ctx = _run_threads_inline()
    try:
        with patch("app.feeds.poll_all_feeds") as poll, patch("app.pipeline.run_pipeline") as run:
            assert client.post(f"{API}/poll", headers=auth(token)).status_code == 200
        poll.assert_called_once()
        run.assert_called_once()
    finally:
        ctx.__exit__(None, None, None)


def test_poll_thread_survives_a_failure(client, app, token, caplog):
    import logging
    from unittest.mock import patch
    caplog.set_level(logging.ERROR, logger="app.api.meta")
    ctx = _run_threads_inline()
    try:
        with patch("app.feeds.poll_all_feeds", side_effect=RuntimeError("netdown")):
            assert client.post(f"{API}/poll", headers=auth(token)).status_code == 200
    finally:
        ctx.__exit__(None, None, None)
    # The request already returned 200; a thread that dies silently would leave
    # the reader waiting for articles that are never coming.
    assert "Manual poll failed" in caplog.text


def test_rescore_hidden_requeues_and_reports_the_count(client, app, token):
    """The requeue is synchronous, so the number returned is one that happened."""
    from unittest.mock import patch
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        for i in range(3):
            add_article(db, fid, seq=i, guid=f"rh{i}", status="hidden")
        db.close()
    ctx = _run_threads_inline()
    try:
        with patch("app.pipeline.run_pipeline") as run:
            body = client.post(f"{API}/rescore-hidden", headers=auth(token)).get_json()
        run.assert_called_once()
    finally:
        ctx.__exit__(None, None, None)
    assert body["requeued"] == 3


def test_rescore_thread_survives_a_failure(client, app, token, caplog):
    import logging
    from unittest.mock import patch
    caplog.set_level(logging.ERROR, logger="app.api.meta")
    ctx = _run_threads_inline()
    try:
        with patch("app.pipeline.run_pipeline", side_effect=RuntimeError("boom")):
            assert client.post(f"{API}/rescore-hidden", headers=auth(token)).status_code == 200
    finally:
        ctx.__exit__(None, None, None)
    assert "Rescore-hidden failed" in caplog.text


def test_status_returns_high_scorers_once(client, app, token):
    """The server tracks who has been told, so a client needs no dedupe."""
    from app.db import get_db_direct, set_setting
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), seq=1, guid="hs", title="Big one", score=0.99)
        set_setting(db, "notify_high_score", "1")
        db.commit()
        db.close()
    first = client.get(f"{API}/status", headers=auth(token)).get_json()["high_score"]
    assert [n["title"] for n in first] == ["Big one"]
    again = client.get(f"{API}/status", headers=auth(token)).get_json()["high_score"]
    assert again == [], "notifying twice is how an alert becomes noise"

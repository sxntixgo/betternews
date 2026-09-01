"""The JSON API and its bearer tokens.

The rule this file exists to enforce: a token authenticates the API, a session
does not, and the two never substitute for one another.
"""

import io

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
    ("get", f"{API}/digest/meta"), ("get", f"{API}/me"),
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
    # /me is GET-only; /feeds accepts POST now, so it stopped being a 405.
    r = client.post(f"{API}/me", headers=auth(token))
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
    r = client.delete("/login")
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
    # The dismissed one leaves the main list rather than sitting in it greyed
    # out, and turns up in the pile the reader has to ask for.
    got = {a["title"]: a["state"]["dismissed"]
           for a in client.get(f"{API}/articles", headers=auth(token)).get_json()["articles"]}
    assert got == {"Other": False}
    pile = client.get(f"{API}/articles?dismissed=1", headers=auth(token)).get_json()
    assert {a["title"] for a in pile["articles"]} == {"Spacey"}


def test_the_dismissed_pile_is_its_own_paged_list(client, app, token):
    """Dismissed articles are reachable, just not in the way.

    They used to stay inline, greyed out. That was itself a correction --
    filtering them out entirely made a dismissal indistinguishable from an
    article that never arrived -- but with `dismiss-all` one button away, those
    rows become most of what a reader scrolls past. So: excluded by default,
    and paged like any other list when asked for.
    """
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        for i in range(5):
            add_article(db, fid, seq=i + 1, guid=f"p{i}", title=f"Story {i}")
        db.close()

    assert client.post(f"{API}/articles/dismiss-all",
                       headers=auth(token)).get_json()["dismissed"] == 5

    # Gone from the default list entirely -- not present-and-flagged.
    assert client.get(f"{API}/articles", headers=auth(token)).get_json()["articles"] == []

    # And paged, so the client can keep scrolling through them.
    first = client.get(f"{API}/articles?dismissed=1&limit=2",
                       headers=auth(token)).get_json()
    assert len(first["articles"]) == 2
    assert first["next_offset"] == 2
    assert all(a["state"]["dismissed"] for a in first["articles"])

    rest = client.get(f"{API}/articles?dismissed=1&limit=2&offset={first['next_offset']}",
                      headers=auth(token)).get_json()
    # No overlap between pages: the offset counts articles the reader sees.
    assert {a["id"] for a in first["articles"]} & {a["id"] for a in rest["articles"]} == set()


def test_dismissing_one_article_takes_it_out_of_the_list(client, app, token):
    """The single-article path and the bulk path agree about where a row goes."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        aid = add_article(db, fid, seq=1, guid="one", title="Only")
        db.close()

    client.post(f"{API}/articles/{aid}/dismiss", headers=auth(token))
    assert client.get(f"{API}/articles", headers=auth(token)).get_json()["articles"] == []
    pile = client.get(f"{API}/articles?dismissed=1", headers=auth(token)).get_json()
    assert [a["id"] for a in pile["articles"]] == [aid]


def test_search_still_finds_a_dismissed_article(client, app, token):
    """The split is about the reading list, not about what exists.

    Someone searching for an article they remember is not asking whether they
    dismissed it afterwards, and hiding it here would read as deleted.
    """
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        aid = add_article(db, fid, seq=1, guid="s1", title="Perihelion flyby")
        db.close()

    client.post(f"{API}/articles/{aid}/dismiss", headers=auth(token))
    assert client.get(f"{API}/articles", headers=auth(token)).get_json()["articles"] == []

    found = client.get(f"{API}/search?q=perihelion", headers=auth(token)).get_json()
    assert [a["id"] for a in found["articles"]] == [aid]


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


# ── phase 5: the reader's own account ─────────────────────────────────────────

def test_register_makes_the_first_account_an_admin(anon, app):
    """Mirrors the HTML path: an empty instance hands the first arrival the keys."""
    from app.db import get_db_direct
    from sqlalchemy import text
    with app.app_context():
        db = get_db_direct()
        db.execute(text("DELETE FROM users"))
        db.commit()
        db.close()
    first = anon.post(f"{API}/auth/register",
                      json={"username": "owner", "password": "a-long-enough-pw"})
    assert first.status_code == 200
    assert first.get_json()["role"] == "admin"

    second = anon.post(f"{API}/auth/register",
                       json={"username": "second", "password": "a-long-enough-pw"})
    assert second.get_json()["role"] == "user"


def test_register_refuses_a_taken_username(anon, registered):
    r = anon.post(f"{API}/auth/register",
                  json={"username": CREDS["username"], "password": "another-long-pw"})
    assert r.status_code == 409


def test_register_enforces_the_same_password_rules_as_the_form(anon, app):
    r = anon.post(f"{API}/auth/register", json={"username": "shorty", "password": "x"})
    assert r.status_code == 400
    assert r.is_json


def test_changing_a_password_requires_the_current_one(client, token, app):
    from app import auth as auth_mod
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        uid = client.application  # noqa: F841
        from app.repo.users import ensure_bootstrap_user
        u = ensure_bootstrap_user(db)
        db.execute(__import__("sqlalchemy").text(
            "UPDATE users SET password_hash = :h WHERE id = :i"),
            {"h": auth_mod.hash_password("current-password-1"), "i": u})
        db.commit()
        db.close()
    bad = client.post(f"{API}/me/password", headers=auth(token),
                      json={"current": "wrong", "new": "new-password-12", "confirm": "new-password-12"})
    assert bad.status_code == 400
    ok = client.post(f"{API}/me/password", headers=auth(token),
                     json={"current": "current-password-1", "new": "new-password-12",
                           "confirm": "new-password-12"})
    assert ok.status_code == 200


def test_tokens_can_be_listed_created_and_revoked(client, token):
    made = client.post(f"{API}/me/tokens", headers=auth(token),
                       json={"name": "iPhone"}).get_json()
    # Shown exactly once, at creation.
    assert made["token"].startswith("bn_")
    assert made["name"] == "iPhone"

    listed = client.get(f"{API}/me/tokens", headers=auth(token)).get_json()["tokens"]
    assert any(t["name"] == "iPhone" for t in listed)
    assert all("token" not in t for t in listed), "a list must never re-show the value"

    tid = next(t["id"] for t in listed if t["name"] == "iPhone")
    assert client.post(f"{API}/me/tokens/{tid}/revoke", headers=auth(token)).status_code == 200
    after = client.get(f"{API}/me/tokens", headers=auth(token)).get_json()["tokens"]
    assert not any(t["id"] == tid for t in after)


def test_a_reader_cannot_revoke_someone_elses_token(client, token, app):
    """The id arrives from a client, so the scope has to be enforced server-side."""
    from app import api_tokens as tok
    from app.db import get_db_direct
    from tests.conftest import add_user
    with app.app_context():
        db = get_db_direct()
        other = add_user(db, username="victim", role="user")
        tok.issue(db, other, "victims phone")
        db.commit()
        theirs = tok.for_user(db, other)[0]["id"]
        db.close()
    r = client.post(f"{API}/me/tokens/{theirs}/revoke", headers=auth(token))
    assert r.status_code == 404, "someone else's token should not even be findable"


def test_preferences_round_trip_with_their_evidence(client, token, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        aid = add_article(db, fid, seq=1, guid="pv", topics=["space"])
        from app.repo.articles import record_vote
        from app.repo.users import ensure_bootstrap_user
        record_vote(db, ensure_bootstrap_user(db), aid, 1)
        db.commit()
        db.close()
    body = client.get(f"{API}/me/preferences", headers=auth(token)).get_json()
    # The evidence is what makes the prose readable as a conclusion.
    assert set(body) >= {"profile_text", "updated_at", "liked", "disliked", "stances"}
    assert body["liked"] == 1

    saved = client.post(f"{API}/me/preferences", headers=auth(token),
                        json={"profile_text": "I like rockets."}).get_json()
    assert saved["profile_text"] == "I like rockets."


def test_a_reader_only_sees_their_own_profile(client, token, app):
    from app import api_tokens as tok
    from app.db import get_db_direct
    from tests.conftest import add_user
    client.post(f"{API}/me/preferences", headers=auth(token),
                json={"profile_text": "mine"})
    with app.app_context():
        db = get_db_direct()
        other = add_user(db, username="nosy", role="user")
        value = tok.issue(db, other, "nosy device")
        db.commit()
        db.close()
    theirs = client.get(f"{API}/me/preferences",
                        headers={"Authorization": f"Bearer {value}"}).get_json()
    assert theirs["profile_text"] != "mine"


def test_topic_stances_come_back_with_their_counts(client, token, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), seq=1, guid="ts", topics=["space"])
        db.close()
    client.post(f"{API}/topics/space/stance", headers=auth(token), json={"stance": "more"})
    rows = client.get(f"{API}/topics", headers=auth(token)).get_json()["topics"]
    space = next(t for t in rows if t["topic"] == "space")
    assert space["stance"] == "more"
    assert space["articles"] >= 1


@pytest.mark.parametrize("payload,expected", [
    ({"password": "a-long-enough-pw"}, "Username is required"),
    ({"username": "x" * 61, "password": "a-long-enough-pw"}, "too long"),
])
def test_register_validates_the_username(anon, payload, expected):
    r = anon.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 400
    assert expected.lower() in r.get_json()["error"].lower()


def test_a_new_password_must_pass_the_same_rules(client, token, app):
    """With the wrong current password this returns earlier, so the rules check
    is only reachable once the current one is right."""
    from sqlalchemy import text
    from app import auth as auth_mod
    from app.db import get_db_direct
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        db.execute(text("UPDATE users SET password_hash = :h WHERE id = :i"),
                   {"h": auth_mod.hash_password("known-current-pw"),
                    "i": ensure_bootstrap_user(db)})
        db.commit()
        db.close()
    r = client.post(f"{API}/me/password", headers=auth(token),
                    json={"current": "known-current-pw", "new": "x", "confirm": "x"})
    assert r.status_code == 400
    assert "password" in r.get_json()["error"].lower()


def test_a_device_needs_a_name(client, token):
    r = client.post(f"{API}/me/tokens", headers=auth(token), json={"name": "  "})
    assert r.status_code == 400
    assert "name" in r.get_json()["error"].lower()


def test_regenerating_a_profile_is_scoped_to_the_caller(client, app, token):
    """Rebuilding everyone's from one button would rewrite a profile its owner
    never asked to change."""
    from unittest.mock import patch
    ctx = _run_threads_inline()
    try:
        with patch("app.pipeline.regenerate_preferences") as regen:
            r = client.post(f"{API}/me/preferences/regenerate", headers=auth(token))
        assert r.status_code == 200
        assert regen.call_args.kwargs["user_id"] is not None
    finally:
        ctx.__exit__(None, None, None)


# ── phase 6: feed management ──────────────────────────────────────────────────

FEED_ADMIN_ENDPOINTS = [
    ("post", f"{API}/feeds"),
    ("delete", f"{API}/feeds/1"),
    ("post", f"{API}/feeds/1/pause"),
    ("post", f"{API}/feeds/1/resume"),
    ("post", f"{API}/feeds/1/threshold"),
    ("post", f"{API}/feeds/1/tags"),
    ("post", f"{API}/feeds/opml"),
]


@pytest.fixture
def plain_token(app):
    from app import api_tokens as tok
    from app.db import get_db_direct
    from tests.conftest import add_user
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="reader2", role="user")
        value = tok.issue(db, uid, "reader2 device")
        db.commit()
        db.close()
    return value


@pytest.mark.parametrize("method,path", FEED_ADMIN_ENDPOINTS)
def test_every_feed_mutation_refuses_a_plain_reader(app, plain_token, method, path):
    """Every one, not a sample -- mirrors the assertion tests/test_auth.py makes
    about the HTML admin routes."""
    c = app.test_client()
    r = getattr(c, method)(path, headers={"Authorization": f"Bearer {plain_token}"})
    assert r.status_code == 403, path
    assert r.is_json


def test_listing_feeds_for_management_carries_the_health(client, app, token):
    from app.db import get_db_direct
    from sqlalchemy import text
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db, title="Broken")
        db.execute(text("UPDATE feeds SET last_error = 'DNS went away', "
                        "consecutive_failures = 3 WHERE id = :i"), {"i": fid})
        db.commit()
        db.close()
    rows = client.get(f"{API}/feeds/manage", headers=auth(token)).get_json()["feeds"]
    got = rows[0]
    # A silent 43-day outage is why the error and the failure count are here.
    assert set(got) >= {"id", "url", "title", "paused", "last_error",
                        "consecutive_failures", "score_threshold", "tags",
                        "last_success_at"}
    assert got["last_error"] == "DNS went away"
    assert got["consecutive_failures"] == 3


def test_adding_a_feed(client, token):
    r = client.post(f"{API}/feeds", headers=auth(token),
                    json={"url": "https://example.com/feed.xml"})
    assert r.status_code == 200
    assert r.get_json()["url"] == "https://example.com/feed.xml"


def test_adding_a_feed_needs_a_url(client, token):
    assert client.post(f"{API}/feeds", headers=auth(token), json={}).status_code == 400


def test_a_duplicate_feed_is_refused(client, app, token):
    client.post(f"{API}/feeds", headers=auth(token), json={"url": "https://dup.example/f"})
    r = client.post(f"{API}/feeds", headers=auth(token), json={"url": "https://dup.example/f"})
    assert r.status_code == 409


def test_pause_resume_threshold_and_tags(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        db.close()
    assert client.post(f"{API}/feeds/{fid}/pause", headers=auth(token)).get_json()["paused"] is True
    assert client.post(f"{API}/feeds/{fid}/resume", headers=auth(token)).get_json()["paused"] is False

    got = client.post(f"{API}/feeds/{fid}/threshold", headers=auth(token),
                      json={"threshold": 0.6}).get_json()
    assert got["score_threshold"] == 0.6

    tagged = client.post(f"{API}/feeds/{fid}/tags", headers=auth(token),
                         json={"tags": "Sports, tech ,, sports"}).get_json()
    # Normalised the same way the form does: trimmed, deduped, lowercased.
    assert tagged["tags"] == ["sports", "tech"]


def test_a_threshold_outside_zero_to_one_is_refused(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        db.close()
    assert client.post(f"{API}/feeds/{fid}/threshold", headers=auth(token),
                       json={"threshold": 5}).status_code == 400


def test_deleting_a_feed(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        db.close()
    assert client.delete(f"{API}/feeds/{fid}", headers=auth(token)).status_code == 200
    remaining = client.get(f"{API}/feeds/manage", headers=auth(token)).get_json()["feeds"]
    assert not any(f["id"] == fid for f in remaining)


def test_opml_round_trips_without_duplicating(client, app, token):
    """Export then import must not double the list -- the ingest is
    ON CONFLICT DO NOTHING, and this proves it."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_feed(db, url="https://a.example/rss", title="A")
        add_feed(db, url="https://b.example/rss", title="B")
        db.close()
    exported = client.get(f"{API}/feeds/opml", headers=auth(token))
    assert exported.status_code == 200
    assert b"<opml" in exported.data
    assert "attachment" in exported.headers["Content-Disposition"]

    before = len(client.get(f"{API}/feeds/manage", headers=auth(token)).get_json()["feeds"])
    r = client.post(f"{API}/feeds/opml", headers=auth(token),
                    data={"file": (io.BytesIO(exported.data), "feeds.opml")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["added"] == 0
    after = len(client.get(f"{API}/feeds/manage", headers=auth(token)).get_json()["feeds"])
    assert after == before


def test_opml_import_adds_new_feeds(client, token):
    opml = (b'<?xml version="1.0"?><opml version="1.0"><body>'
            b'<outline type="rss" text="New" xmlUrl="https://new.example/rss"/>'
            b'</body></opml>')
    r = client.post(f"{API}/feeds/opml", headers=auth(token),
                    data={"file": (io.BytesIO(opml), "in.opml")},
                    content_type="multipart/form-data")
    assert r.get_json()["added"] == 1


@pytest.mark.parametrize("method,path,body", [
    ("delete", "", None),
    ("post", "/pause", None),
    ("post", "/resume", None),
    ("post", "/threshold", {"threshold": 0.5}),
    ("post", "/tags", {"tags": "x"}),
])
def test_acting_on_a_missing_feed_is_a_json_404(client, token, method, path, body):
    r = getattr(client, method)(f"{API}/feeds/999999{path}", headers=auth(token), json=body)
    assert r.status_code == 404
    assert r.is_json


def test_a_non_numeric_threshold_is_refused(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        db.close()
    r = client.post(f"{API}/feeds/{fid}/threshold", headers=auth(token),
                    json={"threshold": "quite high"})
    assert r.status_code == 400


def test_a_null_threshold_clears_it(client, app, token):
    """Falling back to the global threshold is a real choice, not an error."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        db.close()
    client.post(f"{API}/feeds/{fid}/threshold", headers=auth(token), json={"threshold": 0.7})
    got = client.post(f"{API}/feeds/{fid}/threshold", headers=auth(token),
                      json={"threshold": None}).get_json()
    assert got["score_threshold"] is None


def test_tags_accept_a_list_as_well_as_a_string(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        db.close()
    got = client.post(f"{API}/feeds/{fid}/tags", headers=auth(token),
                      json={"tags": ["Tech", "sports"]}).get_json()
    assert got["tags"] == ["sports", "tech"]


def test_opml_import_without_a_file_is_refused(client, token):
    assert client.post(f"{API}/feeds/opml", headers=auth(token)).status_code == 400


def test_opml_import_rejects_something_that_is_not_opml(client, token):
    r = client.post(f"{API}/feeds/opml", headers=auth(token),
                    data={"file": (io.BytesIO(b"not xml at all"), "junk.opml")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "opml" in r.get_json()["error"].lower()


def test_opml_import_rejects_xml_with_no_feeds(client, token):
    """Usually the wrong file rather than an empty subscription list."""
    empty = b'<?xml version="1.0"?><opml version="2.0"><body></body></opml>'
    r = client.post(f"{API}/feeds/opml", headers=auth(token),
                    data={"file": (io.BytesIO(empty), "empty.opml")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "no feeds" in r.get_json()["error"].lower()


# ── phase 7: settings ─────────────────────────────────────────────────────────

SETTINGS_ENDPOINTS = [
    ("get", f"{API}/settings/ollama"), ("post", f"{API}/settings/ollama"),
    ("post", f"{API}/settings/ollama/test"),
    ("get", f"{API}/settings/models"), ("post", f"{API}/settings/models"),
    ("post", f"{API}/settings/models/recommended"),
    ("get", f"{API}/settings/reader"), ("post", f"{API}/settings/reader"),
    ("get", f"{API}/settings/retention"), ("post", f"{API}/settings/retention"),
    ("post", f"{API}/settings/retention/prune"),
    ("post", f"{API}/settings/retention/clear-read"),
    ("get", f"{API}/settings/topics"), ("post", f"{API}/settings/topics"),
]


@pytest.mark.parametrize("method,path", SETTINGS_ENDPOINTS)
def test_every_settings_endpoint_is_admin_only(app, plain_token, method, path):
    c = app.test_client()
    r = getattr(c, method)(path, headers={"Authorization": f"Bearer {plain_token}"}, json={})
    assert r.status_code == 403, path
    assert r.is_json


def test_ollama_settings_round_trip(client, token):
    saved = client.post(f"{API}/settings/ollama", headers=auth(token),
                        json={"host": "ollama", "port": "11434"}).get_json()
    assert saved["host"] == "ollama"
    assert saved["using_env"] is False
    assert "11434" in saved["active_base"]

    cleared = client.post(f"{API}/settings/ollama", headers=auth(token),
                          json={"host": "", "port": ""}).get_json()
    # Blank means fall back to the environment, which the response says outright.
    assert cleared["using_env"] is True


def test_a_nonsense_ollama_host_is_refused_with_a_usable_message(client, token):
    r = client.post(f"{API}/settings/ollama", headers=auth(token),
                    json={"host": "not a host", "port": "banana"})
    assert r.status_code == 400
    assert r.get_json()["error"]


def test_testing_the_connection_does_not_save_it(client, token):
    """Saving first and testing after is how a working configuration gets
    replaced by a broken one."""
    before = client.get(f"{API}/settings/ollama", headers=auth(token)).get_json()
    client.post(f"{API}/settings/ollama/test", headers=auth(token),
                json={"host": "nowhere.invalid", "port": "9999"})
    after = client.get(f"{API}/settings/ollama", headers=auth(token)).get_json()
    assert after["host"] == before["host"]
    assert after["port"] == before["port"]


def test_the_connection_test_reports_why_it_failed(client, token):
    body = client.post(f"{API}/settings/ollama/test", headers=auth(token),
                       json={"host": "127.0.0.1", "port": "1"}).get_json()
    assert body["ok"] is False
    # An endpoint that silently returns [] is how a broken host goes unnoticed.
    assert body["message"]


def test_a_nonsense_host_is_refused_by_the_test_endpoint_too(client, token):
    """Both doors validate. The probe endpoint taking a host the save endpoint
    rejects would report success for something unsaveable."""
    r = client.post(f"{API}/settings/ollama/test", headers=auth(token),
                    json={"host": "not a host", "port": "banana"})
    assert r.status_code == 400
    assert r.get_json()["error"]


def test_models_list_every_job_and_flag_what_is_missing(client, token):
    from unittest.mock import patch
    with patch("app.ollama_client.list_models", return_value=["llama3.2:3b"]):
        body = client.get(f"{API}/settings/models", headers=auth(token)).get_json()
    ids = {a["id"] for a in body["actions"]}
    assert len(ids) == 6, "every job the app runs through Ollama"
    assert all("recommended" in a and "why" in a for a in body["actions"])


def test_models_carry_the_guidance_the_panel_needs(client, token):
    """`guidance`, the JSON/heavy flags and explicit-vs-inherited were computed
    by llm_config and dropped on the floor here, so the panel could not have
    shown them even if it wanted to."""
    from unittest.mock import patch
    with patch("app.ollama_client.list_models", return_value=["llama3.2:3b"]):
        body = client.get(f"{API}/settings/models", headers=auth(token)).get_json()
    scoring = next(a for a in body["actions"] if a["id"] == "scoring")
    assert scoring["guidance"], "the text that stops a silent six-week outage"
    assert scoring["json_output"] is True
    assert scoring["heavy"] is True
    # Nothing configured yet, so it is falling back rather than set.
    assert scoring["inherited"] is True
    assert scoring["explicit"] == ""
    assert scoring["current"], "still resolves to something"


def test_setting_a_model_makes_it_explicit(client, token):
    """The resolved name alone cannot tell "set to X" from "defaulting to X"."""
    from unittest.mock import patch
    with patch("app.ollama_client.list_models", return_value=["llama3.1:8b"]):
        body = client.post(f"{API}/settings/models", headers=auth(token),
                           json={"scoring": "llama3.1:8b"}).get_json()
        scoring = next(a for a in body["actions"] if a["id"] == "scoring")
        assert scoring["explicit"] == "llama3.1:8b"
        assert scoring["inherited"] is False

        cleared = client.post(f"{API}/settings/models", headers=auth(token),
                              json={"scoring": ""}).get_json()
    scoring = next(a for a in cleared["actions"] if a["id"] == "scoring")
    assert scoring["explicit"] == ""
    assert scoring["inherited"] is True


def test_a_reasoning_model_on_a_json_job_is_flagged_as_suboptimal(client, app, token):
    """Reasoning models spend their output budget thinking and often never
    reach the JSON. That is the failure the panel exists to warn about."""
    from unittest.mock import patch
    from app.db import get_db_direct, set_setting
    with app.app_context():
        db = get_db_direct()
        set_setting(db, "model_scoring", "deepseek-r1:8b")
        db.commit()
        db.close()
    with patch("app.ollama_client.list_models",
               return_value=["deepseek-r1:8b", "llama3.2:3b"]):
        body = client.get(f"{API}/settings/models", headers=auth(token)).get_json()
    scoring = next(a for a in body["actions"] if a["id"] == "scoring")
    assert scoring["suboptimal"] is True
    # The free-text jobs are the ones reasoning actually suits.
    digest = next(a for a in body["actions"] if a["id"] == "digest")
    assert digest["suboptimal"] is False


def test_installed_is_unknown_rather_than_false_without_ollama(client, token):
    from unittest.mock import patch
    with patch("app.ollama_client.list_models", return_value=[]):
        body = client.get(f"{API}/settings/models", headers=auth(token)).get_json()
    assert all(a["installed"] is None for a in body["actions"])


def test_saving_an_unknown_job_is_refused(client, token):
    r = client.post(f"{API}/settings/models", headers=auth(token),
                    json={"not_a_job": "llama3.2:3b"})
    assert r.status_code == 400
    assert "not_a_job" in r.get_json()["error"]


def test_models_can_be_set_per_job(client, token):
    from unittest.mock import patch
    with patch("app.ollama_client.list_models", return_value=["llama3.1:8b"]):
        body = client.post(f"{API}/settings/models", headers=auth(token),
                           json={"scoring": "llama3.1:8b"}).get_json()
    scoring = next(a for a in body["actions"] if a["id"] == "scoring")
    assert scoring["current"] == "llama3.1:8b"


def test_applying_recommendations_without_ollama_changes_nothing(client, token):
    from unittest.mock import patch
    with patch("app.ollama_client.list_models", return_value=[]):
        r = client.post(f"{API}/settings/models/recommended", headers=auth(token))
    # Writing guesses would be worse than doing nothing.
    assert r.get_json()["applied"] == 0


def test_applying_recommendations_writes_every_job_at_once(client, token):
    from unittest.mock import patch
    with patch("app.ollama_client.list_models", return_value=["llama3.1:8b"]):
        applied = client.post(f"{API}/settings/models/recommended",
                              headers=auth(token)).get_json()["applied"]
        body = client.get(f"{API}/settings/models", headers=auth(token)).get_json()
    assert applied > 0
    # The point of the button is that nothing is left on a stale model.
    recommended = [a for a in body["actions"] if a["recommended"]]
    assert recommended and all(a["current"] == a["recommended"] for a in recommended)


def test_reader_settings_round_trip(client, token):
    body = client.post(f"{API}/settings/reader", headers=auth(token),
                       json={"declickbait": True, "content_filter_mode": "highlight",
                             "content_filter_llm": True,
                             "notify_high_score": True}).get_json()
    assert body["declickbait"] is True
    assert body["content_filter_mode"] == "highlight"
    assert body["content_filter_llm"] is True
    assert body["notify_high_score"] is True


def test_an_unknown_padding_mode_is_refused(client, token):
    r = client.post(f"{API}/settings/reader", headers=auth(token),
                    json={"content_filter_mode": "sideways"})
    assert r.status_code == 400


def test_retention_ships_inert_and_refuses_to_prune_unconfirmed(client, app, token):
    """The default window is shorter than most existing corpora, so the first
    run would otherwise delete nearly everything."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), seq=1, guid="old")
        db.close()
    state = client.get(f"{API}/settings/retention", headers=auth(token)).get_json()
    assert state["confirmed"] is False
    assert state["days"] == 15

    blocked = client.post(f"{API}/settings/retention/prune", headers=auth(token))
    assert blocked.status_code == 409

    client.post(f"{API}/settings/retention", headers=auth(token), json={"confirmed": True})
    assert client.post(f"{API}/settings/retention/prune",
                       headers=auth(token)).status_code == 200


def test_retention_days_must_be_a_whole_non_negative_number(client, token):
    assert client.post(f"{API}/settings/retention", headers=auth(token),
                       json={"days": "soon"}).status_code == 400
    assert client.post(f"{API}/settings/retention", headers=auth(token),
                       json={"days": -1}).status_code == 400


def test_retention_days_round_trip(client, token):
    body = client.post(f"{API}/settings/retention", headers=auth(token),
                       json={"days": 30}).get_json()
    assert body["days"] == 30
    assert client.get(f"{API}/settings/retention",
                      headers=auth(token)).get_json()["days"] == 30


def test_clear_read_needs_someone_to_clear(client, token):
    assert client.post(f"{API}/settings/retention/clear-read",
                       headers=auth(token), json={}).status_code == 400


def test_clear_read_for_all_users(client, app, token):
    from app.db import get_db_direct
    from app.repo.articles import mark_read
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), seq=1, guid="cr")
        mark_read(db, ensure_bootstrap_user(db), aid)
        db.commit()
        db.close()
    r = client.post(f"{API}/settings/retention/clear-read", headers=auth(token),
                    json={"all_users": True})
    assert r.get_json()["cleared"] >= 1


def test_topic_rules_mute_boost_and_clear(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), seq=1, guid="tr", topics=["crypto"])
        db.close()
    muted = client.post(f"{API}/settings/topics", headers=auth(token),
                        json={"action": "mute", "topic": "crypto"}).get_json()
    assert next(t for t in muted["topics"] if t["topic"] == "crypto")["muted"] is True

    boosted = client.post(f"{API}/settings/topics", headers=auth(token),
                          json={"action": "boost", "topic": "crypto",
                                "adjustment": 0.2}).get_json()
    row = next(t for t in boosted["topics"] if t["topic"] == "crypto")
    assert row["adjustment"] == 0.2 and row["muted"] is False

    cleared = client.post(f"{API}/settings/topics", headers=auth(token),
                          json={"action": "clear", "topic": "crypto"}).get_json()
    row = next(t for t in cleared["topics"] if t["topic"] == "crypto")
    assert row["adjustment"] == 0.0 and row["muted"] is False


def test_a_non_numeric_boost_is_refused(client, token):
    r = client.post(f"{API}/settings/topics", headers=auth(token),
                    json={"action": "boost", "topic": "crypto",
                          "adjustment": "a lot"})
    assert r.status_code == 400
    assert r.get_json()["error"]


def test_tidying_topics_renormalises_stored_slugs(client, app, token):
    """The repair aliases only help if something applies them."""
    from app.db import get_db_direct
    from sqlalchemy import text
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), seq=1, guid="ti", topics=["pol-tica"])
        db.execute(text("UPDATE articles SET topics = ARRAY['pol-tica'] WHERE id = :i"),
                   {"i": aid})
        db.commit()
        db.close()
    r = client.post(f"{API}/settings/topics", headers=auth(token),
                    json={"action": "renormalize"})
    assert r.get_json()["renormalized"] >= 1


def test_an_unknown_topic_action_is_refused(client, token):
    r = client.post(f"{API}/settings/topics", headers=auth(token),
                    json={"action": "explode", "topic": "crypto"})
    assert r.status_code == 400


def test_a_topic_action_needs_a_topic(client, token):
    assert client.post(f"{API}/settings/topics", headers=auth(token),
                       json={"action": "mute"}).status_code == 400


# ── phase 8: admin, insights, call log ────────────────────────────────────────

def _log_call(db, **over):
    """Write one call-log row.

    Straight into the table on purpose: the real writer is a sink inside
    `ollama_client`, and driving it here would test httpx mocking rather than
    the endpoint.
    """
    from app.models import ollama_calls
    row = {"action": "scoring", "model": "llama3.2:3b", "endpoint": "http://x/api/generate",
           "ok": True, "status_code": 200, "duration_ms": 5,
           "request_preview": "a", "response_preview": "b", "error": None}
    row.update(over)
    db.execute(ollama_calls.insert().values(**row))



ADMIN_AREA_ENDPOINTS = [
    ("get", f"{API}/admin/users"),
    ("post", f"{API}/admin/users/1/role"),
    ("post", f"{API}/admin/users/1/delete"),
    ("post", f"{API}/admin/users/1/reset-password"),
    ("get", f"{API}/insights"), ("post", f"{API}/insights/threshold"),
    ("get", f"{API}/ollama-log"), ("post", f"{API}/ollama-log/toggle"),
    ("post", f"{API}/ollama-log/clear"),
]


@pytest.mark.parametrize("method,path", ADMIN_AREA_ENDPOINTS)
def test_every_admin_area_endpoint_refuses_a_plain_reader(app, plain_token, method, path):
    c = app.test_client()
    r = getattr(c, method)(path, headers={"Authorization": f"Bearer {plain_token}"}, json={})
    assert r.status_code == 403, path
    assert r.is_json


def test_listing_users_says_who_you_are(client, token):
    """The client has to know its own row: it must not offer you Delete on
    yourself, and the server refuses it anyway."""
    body = client.get(f"{API}/admin/users", headers=auth(token)).get_json()
    assert body["me"] in [u["id"] for u in body["users"]]
    assert set(body["users"][0]) == {
        "id", "username", "role", "must_change_password", "created_at",
        "last_login_at", "votes", "read_count"}


def test_promoting_and_demoting_a_user(client, app, token):
    from app.db import get_db_direct
    from tests.conftest import add_user
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="promotable", role="user")
        db.commit()
        db.close()
    body = client.post(f"{API}/admin/users/{uid}/role", headers=auth(token),
                       json={"role": "admin"}).get_json()
    assert next(u for u in body["users"] if u["id"] == uid)["role"] == "admin"
    body = client.post(f"{API}/admin/users/{uid}/role", headers=auth(token),
                       json={"role": "user"}).get_json()
    assert next(u for u in body["users"] if u["id"] == uid)["role"] == "user"


def test_an_invalid_role_is_refused(client, token):
    r = client.post(f"{API}/admin/users/1/role", headers=auth(token),
                    json={"role": "superuser"})
    assert r.status_code == 400


def test_role_and_delete_report_a_missing_user(client, token):
    assert client.post(f"{API}/admin/users/9999/role", headers=auth(token),
                       json={"role": "user"}).status_code == 404
    assert client.post(f"{API}/admin/users/9999/delete",
                       headers=auth(token)).status_code == 404
    assert client.post(f"{API}/admin/users/9999/reset-password",
                       headers=auth(token)).status_code == 404


def test_the_last_admin_cannot_be_demoted_or_deleted(client, app, token):
    """An instance with no admin cannot be repaired from inside the app.
    Same rule as the HTML page, asserted separately because it is re-implemented."""
    from app.db import get_db_direct
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        me = ensure_bootstrap_user(db)
        db.close()
    demote = client.post(f"{API}/admin/users/{me}/role", headers=auth(token),
                         json={"role": "user"})
    assert demote.status_code == 409
    assert "last admin" in demote.get_json()["error"]
    assert client.post(f"{API}/admin/users/{me}/delete",
                       headers=auth(token)).status_code == 409


def test_you_cannot_delete_your_own_account(client, app, token):
    from app.db import get_db_direct
    from app.repo.users import ensure_bootstrap_user
    from tests.conftest import add_user
    with app.app_context():
        db = get_db_direct()
        me = ensure_bootstrap_user(db)
        add_user(db, username="spare-admin", role="admin")   # so "last admin" is not the reason
        db.commit()
        db.close()
    r = client.post(f"{API}/admin/users/{me}/delete", headers=auth(token))
    assert r.status_code == 409
    assert "your own account" in r.get_json()["error"]


def test_deleting_a_user(client, app, token):
    from app.db import get_db_direct
    from tests.conftest import add_user
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="doomed", role="user")
        db.commit()
        db.close()
    body = client.post(f"{API}/admin/users/{uid}/delete", headers=auth(token)).get_json()
    assert uid not in [u["id"] for u in body["users"]]


def test_a_password_reset_returns_the_value_once_and_forces_a_change(client, app, token):
    from app.db import get_db_direct
    from tests.conftest import add_user
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="forgot", role="user")
        db.commit()
        db.close()
    body = client.post(f"{API}/admin/users/{uid}/reset-password",
                       headers=auth(token)).get_json()
    assert body["password"], "generated when none is supplied"
    assert body["username"] == "forgot"
    listed = client.get(f"{API}/admin/users", headers=auth(token)).get_json()
    assert next(u for u in listed["users"] if u["id"] == uid)["must_change_password"] is True


def test_a_weak_reset_password_is_refused(client, app, token):
    from app.db import get_db_direct
    from tests.conftest import add_user
    with app.app_context():
        db = get_db_direct()
        uid = add_user(db, username="weak", role="user")
        db.commit()
        db.close()
    r = client.post(f"{API}/admin/users/{uid}/reset-password", headers=auth(token),
                    json={"password": "x"})
    assert r.status_code == 400
    assert r.get_json()["error"]


def test_insights_answers_every_panel_in_one_call(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), seq=1, guid="i1", topics=["economy"])
        db.close()
    body = client.get(f"{API}/insights", headers=auth(token)).get_json()
    assert set(body) == {"threshold", "threshold_default", "threshold_previous",
                         "histogram", "agreement", "suggestion",
                         "per_feed", "per_topic", "pipeline", "runs", "llm_error"}
    # 20 buckets always, including the empty ones -- a histogram with gaps
    # silently rescales.
    assert len(body["histogram"]) == 20


def test_insights_counts_what_is_actually_in_the_database(client, app, token):
    """This used to cross-check the numbers against the HTML page. That page is
    gone, so it checks them against the rows instead -- which is what the HTML
    was standing in for."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db, title="Shared feed")
        add_article(db, fid, seq=1, guid="ins", topics=["economy"])
        db.close()
    body = client.get(f"{API}/insights", headers=auth(token)).get_json()
    assert body["pipeline"]["total"] == 1
    assert [f["feed"] for f in body["per_feed"]] == ["Shared feed"]


def test_no_votes_means_no_threshold_suggestion(client, token):
    """A suggestion from no data would be a number with no meaning."""
    assert client.get(f"{API}/insights", headers=auth(token)).get_json()["suggestion"] is None


def test_applying_a_threshold_sticks(client, token):
    assert client.post(f"{API}/insights/threshold", headers=auth(token),
                       json={"threshold": 0.55}).get_json()["threshold"] == 0.55
    assert client.get(f"{API}/insights", headers=auth(token)).get_json()["threshold"] == 0.55


def test_changing_the_threshold_is_reversible(client, token):
    """Raising it is one click; there was nothing that lowered it again.

    A reader adopted a suggested threshold, every article fell below it, and the
    reading list emptied -- at which point the only control that moved this
    number was a suggestion button that would set the same value again. The old
    number was gone, because `set_setting` overwrites.
    """
    from app.pipeline import SCORE_THRESHOLD

    first = client.get(f"{API}/insights", headers=auth(token)).get_json()
    assert first["threshold_default"] == SCORE_THRESHOLD
    # Never changed, so there is nothing to go back to.
    assert first["threshold_previous"] is None

    client.post(f"{API}/insights/threshold", headers=auth(token), json={"threshold": 0.55})
    client.post(f"{API}/insights/threshold", headers=auth(token), json={"threshold": 0.95})

    body = client.get(f"{API}/insights", headers=auth(token)).get_json()
    assert body["threshold"] == 0.95
    assert body["threshold_previous"] == 0.55      # one step back, not a history
    assert body["threshold_default"] == SCORE_THRESHOLD

    # And the way back works.
    client.post(f"{API}/insights/threshold", headers=auth(token),
                json={"threshold": body["threshold_previous"]})
    assert client.get(f"{API}/insights",
                      headers=auth(token)).get_json()["threshold"] == 0.55


def test_setting_the_same_threshold_twice_does_not_erase_the_way_back(client, token):
    """Otherwise pressing "Use it" twice makes previous == current, and the undo
    button becomes a button that does nothing."""
    client.post(f"{API}/insights/threshold", headers=auth(token), json={"threshold": 0.55})
    client.post(f"{API}/insights/threshold", headers=auth(token), json={"threshold": 0.95})
    client.post(f"{API}/insights/threshold", headers=auth(token), json={"threshold": 0.95})

    body = client.get(f"{API}/insights", headers=auth(token)).get_json()
    assert body["threshold"] == 0.95
    assert body["threshold_previous"] == 0.55


def test_an_insights_threshold_outside_zero_to_one_is_refused(client, token):
    assert client.post(f"{API}/insights/threshold", headers=auth(token),
                       json={"threshold": 1.5}).status_code == 400
    assert client.post(f"{API}/insights/threshold", headers=auth(token),
                       json={"threshold": "high"}).status_code == 400


def test_the_call_log_ships_off_and_can_be_switched_on(client, token):
    body = client.get(f"{API}/ollama-log", headers=auth(token)).get_json()
    assert body["enabled"] is False
    assert body["keep"] == 200
    assert client.post(f"{API}/ollama-log/toggle", headers=auth(token),
                       json={"enabled": True}).get_json()["enabled"] is True
    assert client.get(f"{API}/ollama-log", headers=auth(token)).get_json()["enabled"] is True


def test_the_call_log_shows_both_sides_of_a_call(client, app, token):
    from app.db import get_db_direct
    from app import call_log
    from app.db import set_setting
    with app.app_context():
        db = get_db_direct()
        set_setting(db, call_log.SETTING, "1")
        _log_call(db, ok=False, status_code=500, duration_ms=12,
                  request_preview="the prompt", response_preview="", error="boom")
        db.commit()
        db.close()
    body = client.get(f"{API}/ollama-log", headers=auth(token)).get_json()
    call = body["calls"][0]
    # The tail is where a reasoning model puts its answer; the head is where a
    # malformed prompt shows up. Both sides or the log cannot diagnose anything.
    assert call["request_preview"] == "the prompt"
    assert call["error"] == "boom"
    assert call["ok"] is False
    assert body["summary"]["failed"] == 1


def test_the_call_log_can_be_narrowed_to_failures(client, app, token):
    from app.db import get_db_direct
    from app import call_log
    from app.db import set_setting
    with app.app_context():
        db = get_db_direct()
        set_setting(db, call_log.SETTING, "1")
        _log_call(db)
        _log_call(db, action="summary", ok=False, status_code=500,
                  request_preview="c", response_preview="", error="nope")
        db.commit()
        db.close()
    all_calls = client.get(f"{API}/ollama-log", headers=auth(token)).get_json()
    failed = client.get(f"{API}/ollama-log?failed=1", headers=auth(token)).get_json()
    assert len(all_calls["calls"]) == 2
    assert [c["ok"] for c in failed["calls"]] == [False]
    assert failed["only_failed"] is True


def test_an_empty_log_still_reports_the_queue(client, token):
    """An empty log means either no calls are being made or none are needed.
    The queue is what tells them apart."""
    body = client.get(f"{API}/ollama-log", headers=auth(token)).get_json()
    assert body["calls"] == []
    assert "queue" in body and isinstance(body["queue"], dict)


def test_clearing_the_call_log(client, app, token):
    from app.db import get_db_direct
    from app import call_log
    from app.db import set_setting
    with app.app_context():
        db = get_db_direct()
        set_setting(db, call_log.SETTING, "1")
        _log_call(db)
        db.commit()
        db.close()
    assert client.post(f"{API}/ollama-log/clear", headers=auth(token)).get_json()["cleared"] == 1
    assert client.get(f"{API}/ollama-log", headers=auth(token)).get_json()["calls"] == []


def test_insights_reports_recent_runs_with_their_duration(client, app, token):
    """A run reporting 0 scored in ~0s is a failing run, not an idle one --
    which is only visible if the duration comes through."""
    from sqlalchemy import text as _t
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        db.execute(_t(
            "INSERT INTO pipeline_runs (started_at, finished_at, scored_n, "
            "summarized_n, errors_n, skipped) "
            "VALUES (now() - interval '90 seconds', now(), 12, 9, 1, false)"))
        db.commit()
        db.close()
    run = client.get(f"{API}/insights", headers=auth(token)).get_json()["runs"][0]
    assert run["scored_n"] == 12 and run["summarized_n"] == 9
    assert run["errors_n"] == 1 and run["skipped"] is False
    assert 85 <= run["seconds"] <= 95
    assert run["started_at"] and run["finished_at"]


# ── phase 9: why the list is empty ────────────────────────────────────────────
# A bare "nothing to read" is how a misconfigured model went unnoticed three
# times. With the HTML empty state gone, this is the only thing that says why.

def test_an_empty_list_says_there_are_no_feeds(client, token):
    body = client.get(f"{API}/articles", headers=auth(token)).get_json()
    assert body["articles"] == []
    assert body["diagnosis"]["kind"] == "no_feeds"
    assert body["diagnosis"]["title"]
    assert body["diagnosis"]["admin_only"] is True


def test_an_empty_list_with_feeds_but_no_articles_says_so(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_feed(db)
        db.commit()
        db.close()
    body = client.get(f"{API}/articles", headers=auth(token)).get_json()
    assert body["diagnosis"]["kind"] == "not_polled"


def test_everything_below_the_threshold_is_diagnosed_as_hidden(client, app, token):
    from sqlalchemy import text as _t
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db), seq=1, guid="h1")
        db.execute(_t("UPDATE articles SET status='hidden' WHERE id=:i"), {"i": aid})
        db.commit()
        db.close()
    body = client.get(f"{API}/articles", headers=auth(token)).get_json()
    assert body["diagnosis"]["kind"] == "all_hidden"
    # A reader can act on this one themselves, unlike an unreachable Ollama.
    assert body["diagnosis"]["admin_only"] is False


def test_a_populated_list_is_not_diagnosed(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), seq=1, guid="d1")
        db.close()
    assert client.get(f"{API}/articles",
                      headers=auth(token)).get_json()["diagnosis"] is None


def test_an_empty_second_page_is_not_diagnosed(client, app, token):
    """The end of the list is not a problem, and diagnosing it costs an Ollama
    probe on every scroll to the bottom."""
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), seq=1, guid="d2")
        db.close()
    body = client.get(f"{API}/articles?offset=50", headers=auth(token)).get_json()
    assert body["articles"] == []
    assert body["diagnosis"] is None


def test_the_diagnosis_carries_a_label_not_a_url(client, token):
    """`diagnose` still names an href for the old server-rendered links. A
    client owns its own navigation, so only the label crosses the wire."""
    d = client.get(f"{API}/articles", headers=auth(token)).get_json()["diagnosis"]
    assert d["action"] == "Manage feeds"
    assert "/" not in (d["action"] or "")


def test_the_list_can_be_filtered_by_feed_and_by_saved(client, app, token):
    """Both filters lost their only coverage with the HTML routes. They are the
    sidebar and the saved section, so they are not incidental."""
    from app.db import get_db_direct
    from app.repo.articles import toggle_saved
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        keep, other = add_feed(db, url="http://a.example/f"), add_feed(db, url="http://b.example/f")
        a1 = add_article(db, keep, seq=1, guid="f1", title="From the kept feed")
        add_article(db, other, seq=2, guid="f2", title="From the other feed")
        toggle_saved(db, ensure_bootstrap_user(db), a1)
        db.commit()
        db.close()

    by_feed = client.get(f"{API}/articles?feed={keep}", headers=auth(token)).get_json()
    assert [a["title"] for a in by_feed["articles"]] == ["From the kept feed"]

    saved = client.get(f"{API}/articles?saved=1", headers=auth(token)).get_json()
    assert [a["title"] for a in saved["articles"]] == ["From the kept feed"]


def test_dismiss_all_respects_the_feed_and_saved_filters(client, app, token):
    """Dismissing has to mean the list on screen, or it removes something the
    reader cannot see."""
    from app.db import get_db_direct
    from app.repo.articles import toggle_saved
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        target, spared = add_feed(db, url="http://x.example/f"), add_feed(db, url="http://y.example/f")
        add_article(db, target, seq=1, guid="da1")
        add_article(db, spared, seq=2, guid="da2")
        db.commit()
        db.close()

    dismissed = client.post(f"{API}/articles/dismiss-all?feed={target}",
                            headers=auth(token)).get_json()
    assert dismissed["dismissed"] == 1
    left = client.get(f"{API}/articles?feed={spared}", headers=auth(token)).get_json()
    assert [a["state"]["dismissed"] for a in left["articles"]] == [False]

    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, spared, seq=3, guid="da3")
        toggle_saved(db, ensure_bootstrap_user(db), aid)
        db.commit()
        db.close()
    assert client.post(f"{API}/articles/dismiss-all?saved=1",
                       headers=auth(token)).get_json()["dismissed"] == 1


# ── prompt inspection and editing ─────────────────────────────────────────────
# Prompts are templates, not prose: `scoring_prompt` interpolates six things and
# dropping one does not raise, it produces a confident score for an article the
# model never saw. So the opinions are editable and the contracts are not.

def test_prompts_show_what_is_actually_sent(client, app, token):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db), seq=1, guid="pr", raw_snippet="Body text here.")
        db.close()
    body = client.get(f"{API}/settings/prompts", headers=auth(token)).get_json()
    ids = {r["id"] for r in body["rendered"]}
    assert {"scoring", "scoring_batch", "summary", "profile", "digest"} <= ids
    scoring = next(r for r in body["rendered"] if r["id"] == "scoring")
    # The whole thing, not the 1,500-character truncation the call log stores.
    assert len(scoring["text"]) > 1500
    assert "Body text here." in scoring["text"], "renders with a real article"


def test_every_editable_slot_reports_its_default(client, token):
    body = client.get(f"{API}/settings/prompts", headers=auth(token)).get_json()
    slots = {s["id"]: s for s in body["slots"]}
    assert {"scoring_rules", "kinds", "tag_range", "profile_framing"} == set(slots)
    for s in slots.values():
        assert s["is_default"] is True
        assert s["value"] == s["default"]
        assert s["label"] and s["help"]


def test_editing_a_slot_changes_the_rendered_prompt(client, token):
    body = client.post(f"{API}/settings/prompts", headers=auth(token),
                       json={"slot": "tag_range", "value": "2-3"}).get_json()
    scoring = next(r for r in body["rendered"] if r["id"] == "scoring")
    assert "2-3 lowercase" in scoring["text"]
    assert next(s for s in body["slots"] if s["id"] == "tag_range")["is_default"] is False


def test_an_empty_value_resets_to_the_default(client, token):
    client.post(f"{API}/settings/prompts", headers=auth(token),
                json={"slot": "tag_range", "value": "2-3"})
    body = client.post(f"{API}/settings/prompts", headers=auth(token),
                       json={"slot": "tag_range", "value": ""}).get_json()
    slot = next(s for s in body["slots"] if s["id"] == "tag_range")
    assert slot["is_default"] is True and slot["value"] == "4-8"


def test_an_edit_that_would_break_the_scorer_is_refused(client, token):
    """The check renders the real prompts with the edit applied rather than
    trusting that a slot only affects itself."""
    r = client.post(f"{API}/settings/prompts", headers=auth(token),
                    json={"slot": "kinds", "value": "only-one — nothing else"})
    assert r.status_code == 400
    assert "at least two" in r.get_json()["error"].lower()


@pytest.mark.parametrize("value,fragment", [
    ("9-2", "low first"),
    ("banana", "range like"),
    ("1-99", "between 1 and 12"),
])
def test_a_nonsense_tag_range_is_refused(client, token, value, fragment):
    r = client.post(f"{API}/settings/prompts", headers=auth(token),
                    json={"slot": "tag_range", "value": value})
    assert r.status_code == 400
    assert fragment in r.get_json()["error"]


def test_kinds_must_each_carry_a_description(client, token):
    r = client.post(f"{API}/settings/prompts", headers=auth(token),
                    json={"slot": "kinds", "value": "alpha\nbeta — has one"})
    assert r.status_code == 400
    assert "description" in r.get_json()["error"]


def test_an_unknown_slot_is_refused(client, token):
    assert client.post(f"{API}/settings/prompts", headers=auth(token),
                       json={"slot": "everything", "value": "x"}).status_code == 400


def test_an_edited_vocabulary_reaches_the_scorer(client, app, token):
    """The point of the feature: change the kinds and the model is told about
    the new ones, not the built-in list."""
    client.post(f"{API}/settings/prompts", headers=auth(token),
                json={"slot": "kinds",
                      "value": "opinion — someone arguing\nreport — what happened"})
    body = client.get(f"{API}/settings/prompts", headers=auth(token)).get_json()
    scoring = next(r for r in body["rendered"] if r["id"] == "scoring")
    assert "opinion — someone arguing" in scoring["text"]
    assert "fixture —" not in scoring["text"], "the built-in list is gone"


def test_the_locked_parts_are_named(client, token):
    """A reader should be able to see what they are not allowed to break."""
    body = client.get(f"{API}/settings/prompts", headers=auth(token)).get_json()
    assert len(body["locked"]) >= 3
    assert any("inject" in w or "data, not instructions" in w for w in body["locked"])

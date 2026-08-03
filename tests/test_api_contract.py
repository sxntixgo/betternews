"""The API and `shared/api.ts` must describe the same thing.

Two clients now read that file, and it was written from observed responses
rather than generated. Nothing connected the two, so renaming a field in
`app/api/serializers.py` would leave both the web app and the phone reading a
key that no longer exists -- and every Python test would still pass.

The check lives here, on the Python side, because that is where the change that
breaks it gets made.
"""

import re
from pathlib import Path

import pytest

from app import api_tokens
from tests.conftest import add_article, add_feed

CONTRACT = Path(__file__).resolve().parent.parent / "shared" / "api.ts"


def declared_fields(interface: str) -> set[str]:
    """Field names from `export interface <name> { ... }`.

    Deliberately a parser rather than a hard-coded list: a hard-coded list is a
    third place to forget to update.
    """
    src = CONTRACT.read_text()
    # \b matters: without it "Article" also matches "ArticleState", and the
    # comparison silently runs against the wrong interface.
    m = re.search(rf"export interface {interface}\b[^{{]*\{{(.*?)\n\}}", src, re.S)
    assert m, f"{interface} not found in shared/api.ts"
    body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)      # block comments
    body = re.sub(r"//.*", "", body)                             # line comments
    return set(re.findall(r"^\s*([a-z_]+)\??:", body, re.M))


@pytest.fixture
def token(app):
    from app.db import get_db_direct
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        value = api_tokens.issue(db, ensure_bootstrap_user(db), "contract")
        db.commit()
        db.close()
    return {"Authorization": f"Bearer {value}"}


@pytest.fixture
def seeded(app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        aid = add_article(db, add_feed(db, title="A feed"), seq=1, guid="c1",
                          topics=["economy"], full_text="Body text.")
        db.close()
    return aid


def test_the_contract_file_is_where_this_expects(app):
    assert CONTRACT.exists(), (
        "shared/api.ts moved. Both clients import it; update this test with it.")


def test_article_fields_match_the_contract(client, token, seeded):
    got = client.get("/api/v1/articles", headers=token).get_json()["articles"][0]
    declared = declared_fields("Article")
    assert set(got) == declared, (
        f"serializer emits {set(got) - declared or '{}'} not in shared/api.ts; "
        f"contract declares {declared - set(got) or '{}'} the API never sends")


def test_article_state_fields_match_the_contract(client, token, seeded):
    got = client.get("/api/v1/articles", headers=token).get_json()["articles"][0]
    assert set(got["state"]) == declared_fields("ArticleState")


def test_article_detail_fields_match_the_contract(client, token, seeded):
    got = client.get(f"/api/v1/articles/{seeded}", headers=token).get_json()
    # ArticleDetail extends Article, so both sets of keys have to be present.
    declared = declared_fields("ArticleDetail") | declared_fields("Article")
    assert set(got) == declared


def test_page_fields_match_the_contract(client, token, seeded):
    got = client.get("/api/v1/articles", headers=token).get_json()
    assert set(got) == declared_fields("ArticlePage")


def test_feed_fields_match_the_contract(client, token, seeded):
    body = client.get("/api/v1/feeds", headers=token).get_json()
    assert set(body) == declared_fields("FeedList")
    assert set(body["feeds"][0]) == declared_fields("Feed")


def test_me_fields_match_the_contract(client, token):
    assert set(client.get("/api/v1/me", headers=token).get_json()) == declared_fields("Me")


def test_topic_fields_match_the_contract(client, token, seeded):
    got = client.get("/api/v1/topics", headers=token).get_json()["topics"]
    assert got, "seed an article with topics or this asserts nothing"
    assert set(got[0]) == declared_fields("Topic")


def test_digest_fields_match_the_contract(client, app, token):
    from unittest.mock import patch
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        for i in range(6):
            add_article(db, fid, seq=i, guid=f"dg{i}")
        db.close()
    with patch("app.ollama_client.generate", return_value="**Theme**\nBrief."):
        got = client.get("/api/v1/digest", headers=token).get_json()
    assert set(got) == declared_fields("Digest")


def test_opinion_values_match_the_declared_union(client, token, seeded):
    """`opinion` is a union in the contract, so the API must not invent a third."""
    src = CONTRACT.read_text()
    m = re.search(r"export type Opinion = ([^;]+);", src)
    assert m, "Opinion union not found"
    allowed = set(re.findall(r"'([a-z]+)'", m.group(1)))

    for value, expected in ((1, "liked"), (-1, "disliked")):
        got = client.post(f"/api/v1/articles/{seeded}/vote", json={"value": value},
                          headers=token).get_json()
        assert got["state"]["opinion"] == expected
        assert expected in allowed


def test_status_fields_match_the_contract(client, token, seeded):
    got = client.get("/api/v1/status", headers=token).get_json()
    assert set(got) == declared_fields("Status")


# ── settings ──────────────────────────────────────────────────────────────────
# Seven panels behind bespoke endpoints, so seven shapes a client can rely on.
# These are the ones most likely to drift: nothing else reads them.

def test_ollama_settings_fields_match_the_contract(client, token):
    got = client.get("/api/v1/settings/ollama", headers=token).get_json()
    assert set(got) == declared_fields("OllamaSettings")


def test_ollama_probe_fields_match_the_contract(client, token):
    got = client.post("/api/v1/settings/ollama/test", headers=token,
                      json={"host": "127.0.0.1", "port": "1"}).get_json()
    assert set(got) == declared_fields("OllamaProbe")


def test_model_settings_fields_match_the_contract(client, token):
    got = client.get("/api/v1/settings/models", headers=token).get_json()
    assert set(got) == declared_fields("ModelSettings")
    assert got["actions"], "every Ollama job should be listed"
    assert set(got["actions"][0]) == declared_fields("ModelAction")


def test_reader_settings_fields_match_the_contract(client, token):
    got = client.get("/api/v1/settings/reader", headers=token).get_json()
    assert set(got) == declared_fields("ReaderSettings")


def test_retention_settings_fields_match_the_contract(client, token):
    got = client.get("/api/v1/settings/retention", headers=token).get_json()
    assert set(got) == declared_fields("RetentionSettings")


def test_topic_rule_fields_match_the_contract(client, token, seeded):
    got = client.get("/api/v1/settings/topics", headers=token).get_json()["topics"]
    assert got, "seed an article with topics or this asserts nothing"
    assert set(got[0]) == declared_fields("TopicRule")


def test_managed_feed_fields_match_the_contract(client, token, seeded):
    got = client.get("/api/v1/feeds/manage", headers=token).get_json()["feeds"][0]
    assert set(got) == declared_fields("ManagedFeed")


# ── admin and ops ─────────────────────────────────────────────────────────────

def test_admin_user_fields_match_the_contract(client, token):
    body = client.get("/api/v1/admin/users", headers=token).get_json()
    assert set(body) == declared_fields("AdminUserList")
    assert set(body["users"][0]) == declared_fields("AdminUser")


def test_insights_fields_match_the_contract(client, token, seeded):
    got = client.get("/api/v1/insights", headers=token).get_json()
    assert set(got) == declared_fields("Insights")
    assert set(got["histogram"][0]) == declared_fields("HistogramBucket")
    assert set(got["agreement"]) == declared_fields("Agreement")
    assert set(got["per_feed"][0]) == declared_fields("FeedAccuracy")


def test_pipeline_run_fields_match_the_contract(client, app, token):
    from sqlalchemy import text as _t
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        db.execute(_t("INSERT INTO pipeline_runs (started_at, finished_at, scored_n) "
                      "VALUES (now(), now(), 1)"))
        db.commit()
        db.close()
    got = client.get("/api/v1/insights", headers=token).get_json()["runs"][0]
    assert set(got) == declared_fields("PipelineRun")


def test_ollama_log_fields_match_the_contract(client, app, token):
    from app.models import ollama_calls
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        db.execute(ollama_calls.insert().values(
            action="scoring", model="m", endpoint="e", ok=True, status_code=200,
            duration_ms=5, request_preview="a", response_preview="b", error=None))
        db.commit()
        db.close()
    body = client.get("/api/v1/ollama-log", headers=token).get_json()
    assert set(body) == declared_fields("OllamaLog")
    assert set(body["calls"][0]) == declared_fields("OllamaCall")


def test_a_field_declared_as_a_string_is_sent_as_one(client, app, token):
    """Field *names* matching is not the same as types matching.

    `last_run` is declared `string | null` and was sent as the whole pipeline
    run row, because the helper that stringifies timestamps only converts
    things with `.isoformat()` and a dict fell straight through. The client
    called .slice() on it and the screen went blank. Names alone could not
    catch that.
    """
    from sqlalchemy import text as _t
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        db.execute(_t("INSERT INTO pipeline_runs (started_at, finished_at, scored_n) "
                      "VALUES (now(), now(), 3)"))
        db.commit()
        db.close()
    body = client.get("/api/v1/ollama-log", headers=token).get_json()
    assert isinstance(body["last_run"], str), \
        f"declared string, sent {type(body['last_run']).__name__}"
    assert body["last_run"].startswith("20")

    insights = client.get("/api/v1/insights", headers=token).get_json()
    run = insights["runs"][0]
    for field in ("started_at", "finished_at"):
        assert isinstance(run[field], str), field


def test_diagnosis_fields_match_the_contract(client, token):
    """The empty-list explanation. Its `kind` is a union the client branches on,
    so an unlisted value would silently fall through to a default."""
    import re as _re
    got = client.get("/api/v1/articles", headers=token).get_json()["diagnosis"]
    assert set(got) == declared_fields("Diagnosis")

    src = CONTRACT.read_text()
    m = _re.search(r"export interface Diagnosis\b[^{]*\{(.*?)\n\}", src, _re.S)
    allowed = set(_re.findall(r"'([a-z_]+)'", m.group(1)))
    from app import pipeline_status
    # Every kind the server can emit has to be in the union.
    emitted = set(_re.findall(r'"kind": "([a-z_]+)"',
                              __import__("inspect").getsource(pipeline_status.diagnose)))
    assert emitted <= allowed, f"kinds missing from the contract: {emitted - allowed}"

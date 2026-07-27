"""Per-action model selection.

The app makes six kinds of Ollama call with different requirements; this is
where each one's model is chosen, and where a model that isn't installed is
made visible rather than failing silently on every call.
"""

from unittest.mock import patch

import pytest

from app import llm_config
from app.db import set_setting


ALL_IDS = [a.id for a in llm_config.ACTIONS]


def test_every_generate_call_site_has_an_action():
    """If a new Ollama call is added without registering it, this fails."""
    import re
    from pathlib import Path
    prompts_used = set()
    for f in Path("app").glob("*.py"):
        prompts_used |= set(re.findall(r"prompt=prompts\.(\w+)", f.read_text()))
    # Each prompt builder belongs to exactly one configurable action.
    mapping = {
        "scoring_prompt": "scoring", "batch_scoring_prompt": "scoring",
        "summarization_prompt": "summary", "summarization_with_title_prompt": "summary",
        "transcript_summarization_prompt": "transcript",
        "aside_prompt": "asides", "profile_prompt": "profile",
        "digest_prompt": "digest",
    }
    assert prompts_used <= set(mapping), f"unregistered prompt: {prompts_used - set(mapping)}"
    assert set(mapping.values()) == set(ALL_IDS)


# ── resolution ─────────────────────────────────────────────────────────────────

def test_unset_actions_fall_back_to_the_env_default(db_conn):
    from app.pipeline import DEFAULT_SCORING_MODEL, DEFAULT_SUMMARY_MODEL
    assert llm_config.model_for(db_conn, "scoring") == DEFAULT_SCORING_MODEL
    assert llm_config.model_for(db_conn, "digest") == DEFAULT_SUMMARY_MODEL


@pytest.mark.parametrize("action_id", ALL_IDS)
def test_an_explicit_choice_wins(db_conn, action_id):
    llm_config.set_model(db_conn, action_id, "custom:7b")
    db_conn.commit()
    assert llm_config.model_for(db_conn, action_id) == "custom:7b"


def test_existing_installs_keep_working(db_conn):
    """summary_model was the only setting before this; it must still apply."""
    set_setting(db_conn, "summary_model", "legacy:8b")
    set_setting(db_conn, "scoring_model", "legacyscore:8b")
    db_conn.commit()
    assert llm_config.model_for(db_conn, "digest") == "legacy:8b"
    assert llm_config.model_for(db_conn, "asides") == "legacy:8b"
    assert llm_config.model_for(db_conn, "scoring") == "legacyscore:8b"


def test_a_per_action_choice_overrides_the_legacy_setting(db_conn):
    set_setting(db_conn, "summary_model", "legacy:8b")
    llm_config.set_model(db_conn, "digest", "special:70b")
    db_conn.commit()
    assert llm_config.model_for(db_conn, "digest") == "special:70b"
    assert llm_config.model_for(db_conn, "summary") == "legacy:8b"   # unaffected


def test_clearing_a_choice_reverts_to_the_fallback(db_conn):
    set_setting(db_conn, "summary_model", "legacy:8b")
    llm_config.set_model(db_conn, "digest", "special:70b")
    llm_config.set_model(db_conn, "digest", "")
    db_conn.commit()
    assert llm_config.model_for(db_conn, "digest") == "legacy:8b"


def test_unknown_action_is_rejected(db_conn):
    with pytest.raises(ValueError):
        llm_config.set_model(db_conn, "nonsense", "x")


# ── reporting ──────────────────────────────────────────────────────────────────

def test_current_lists_every_action(db_conn):
    assert [r["action"].id for r in llm_config.current(db_conn)] == ALL_IDS


def test_current_flags_an_uninstalled_model(db_conn):
    """Exactly the failure that hid for six weeks: a model configured here but
    absent from the server."""
    llm_config.set_model(db_conn, "scoring", "ministral-3:14b")
    db_conn.commit()
    rows = {r["action"].id: r for r in llm_config.current(db_conn, ["llama3.1:8b"])}
    assert rows["scoring"]["missing"] is True
    assert rows["summary"]["missing"] is True     # falls back to an absent default


def test_nothing_is_flagged_when_the_model_list_is_unknown(db_conn):
    """Ollama being unreachable must not paint every row red."""
    assert all(not r["missing"] for r in llm_config.current(db_conn, []))


def test_inherited_is_reported(db_conn):
    llm_config.set_model(db_conn, "scoring", "explicit:1b")
    db_conn.commit()
    rows = {r["action"].id: r for r in llm_config.current(db_conn)}
    assert rows["scoring"]["inherited"] is False
    assert rows["digest"]["inherited"] is True


# ── the pipeline actually uses them ────────────────────────────────────────────

def test_scoring_uses_the_scoring_model(db_conn):
    from app.pipeline import score_new_articles
    from tests.conftest import add_article, add_feed
    llm_config.set_model(db_conn, "scoring", "scorer:1b")
    db_conn.commit()
    add_article(db_conn, add_feed(db_conn), status="new", score=None)
    with patch("app.pipeline.ollama_client.generate",
               return_value={"score": 0.9, "reason": "r"}) as gen:
        score_new_articles(db_conn, "p")
    assert gen.call_args.kwargs["model"] == "scorer:1b"


def test_summaries_and_transcripts_can_differ(db_conn):
    from app.pipeline import summarize_scored_articles
    from tests.conftest import add_article, add_feed
    llm_config.set_model(db_conn, "summary", "prose:8b")
    llm_config.set_model(db_conn, "transcript", "longctx:8b")
    db_conn.commit()
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="a", status="scored",
                url="https://example.com/a")
    add_article(db_conn, fid, seq=2, guid="b", status="scored",
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    with patch("app.pipeline.extract.extract", return_value=("body " * 60, None, "http")), \
         patch("app.pipeline.youtube.transcript", return_value="spoken words"), \
         patch("app.pipeline.ollama_client.generate", return_value="S.") as gen:
        summarize_scored_articles(db_conn)
    used = {c.kwargs["model"] for c in gen.call_args_list}
    assert used == {"prose:8b", "longctx:8b"}


def test_profile_regeneration_uses_its_own_model(db_conn, app):
    from app.pipeline import regenerate_preferences
    from app.repo.articles import record_vote
    from app.repo.users import ensure_bootstrap_user
    from tests.conftest import add_article, add_feed
    llm_config.set_model(db_conn, "profile", "thinker:70b")
    uid = ensure_bootstrap_user(db_conn)
    record_vote(db_conn, uid, add_article(db_conn, add_feed(db_conn)), 1)
    db_conn.commit()
    with patch("app.pipeline.ollama_client.generate", return_value="profile") as gen:
        regenerate_preferences(app)
    assert gen.call_args.kwargs["model"] == "thinker:70b"


def test_digest_uses_its_own_model(client, app):
    from app.db import get_db_direct
    from tests.conftest import add_article, add_feed
    with app.app_context():
        db = get_db_direct()
        llm_config.set_model(db, "digest", "briefer:8b")
        fid = add_feed(db)
        for i in range(3):
            add_article(db, fid, seq=i, guid=f"g{i}")
        db.commit()
        db.close()
    with patch("app.ollama_client.generate", return_value="brief") as gen:
        client.get("/digest")
    assert gen.call_args.kwargs["model"] == "briefer:8b"


def test_aside_detection_uses_its_own_model(db_conn):
    from app.pipeline import summarize_scored_articles
    from app.db import set_setting as ss
    from tests.conftest import add_article, add_feed
    llm_config.set_model(db_conn, "summary", "prose:8b")
    llm_config.set_model(db_conn, "asides", "picker:3b")
    ss(db_conn, "content_filter_llm", "1")
    db_conn.commit()
    add_article(db_conn, add_feed(db_conn), status="scored")
    with patch("app.pipeline.extract.extract",
               return_value=("one\ntwo\nthree\nfour", None, "http")), \
         patch("app.pipeline.ollama_client.generate",
               side_effect=["S.", {"asides": []}]) as gen:
        summarize_scored_articles(db_conn)
    assert [c.kwargs["model"] for c in gen.call_args_list] == ["prose:8b", "picker:3b"]


# ── settings panel ─────────────────────────────────────────────────────────────

@patch("app.routes.ollama_client.list_models", return_value=["llama3.1:8b", "qwen:7b"])
def test_panel_lists_every_job_and_the_installed_models(mock_list, client):
    data = client.get("/settings/models").get_data(as_text=True)
    for action in llm_config.ACTIONS:
        assert action.label in data
    assert "llama3.1:8b" in data and "qwen:7b" in data


@patch("app.routes.ollama_client.list_models", return_value=["llama3.1:8b"])
def test_panel_warns_about_an_uninstalled_model(mock_list, client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        llm_config.set_model(db, "scoring", "ministral-3:14b")
        db.commit()
        db.close()
    data = client.get("/settings/models").get_data(as_text=True)
    assert "not installed" in data
    assert "will fail every time" in data


@patch("app.routes.ollama_client.list_models", return_value=[])
def test_panel_says_so_when_ollama_is_unreachable(mock_list, client):
    assert b"Could not reach Ollama" in client.get("/settings/models").data


@patch("app.routes.ollama_client.list_models", return_value=["llama3.1:8b"])
def test_saving_one_job_does_not_touch_the_others(mock_list, client, app):
    r = client.post("/settings/models",
                    data={"action_id": "digest", "model": "llama3.1:8b"})
    assert r.status_code == 200
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        assert llm_config.model_for(db, "digest") == "llama3.1:8b"
        rows = {r["action"].id: r for r in llm_config.current(db)}
        assert rows["scoring"]["inherited"] is True
        db.close()


@patch("app.routes.ollama_client.list_models", return_value=["llama3.1:8b"])
def test_saving_an_unknown_job_is_rejected(mock_list, client):
    assert client.post("/settings/models",
                       data={"action_id": "bogus", "model": "x"}).status_code == 400


def test_model_settings_are_admin_only(login_as):
    c, _ = login_as()
    assert c.get("/settings/models").status_code == 403
    assert c.post("/settings/models",
                  data={"action_id": "digest", "model": "x"}).status_code == 403


@patch("app.routes.ollama_client.list_models", return_value=["llama3.1:8b"])
def test_panel_queries_the_configured_endpoint(mock_list, client, app):
    """The model list must come from the server the app actually calls."""
    from app.db import get_db_direct, set_setting as ss
    with app.app_context():
        db = get_db_direct()
        ss(db, "ollama_host", "ollama.lan"); ss(db, "ollama_port", "80")
        db.commit(); db.close()
    client.get("/settings/models")
    mock_list.assert_called_once_with("http://ollama.lan:80")


# ── recommendations ────────────────────────────────────────────────────────────

INSTALLED = ["llama3.2:latest", "llama3.1:8b", "gpt-oss:20b"]


@pytest.mark.parametrize("name,expected", [
    ("gpt-oss:20b", True), ("deepseek-r1:8b", True), ("qwq:32b", True),
    ("magistral:24b", True), ("llama3.1:8b", False), ("mistral:7b", False),
    ("llama3.2:latest", False), ("", False),
])
def test_reasoning_models_are_recognised(name, expected):
    assert llm_config.is_reasoning_model(name) is expected


@pytest.mark.parametrize("name,expected", [
    ("llama3.1:8b", 8), ("gpt-oss:20b", 20), ("qwen2.5:14b", 14),
    ("phi3:3.8b", 3.8), ("llama3.2:latest", None), ("mistral", None),
])
def test_parameter_size_is_read_from_the_tag(name, expected):
    assert llm_config.model_size_b(name) == expected


@pytest.mark.parametrize("action_id", ["scoring", "summary", "asides"])
def test_per_article_jobs_avoid_reasoning_models(action_id):
    """Reasoning on every article is the failure that produced empty responses
    and truncated JSON."""
    model, why = llm_config.recommend(action_id, INSTALLED)
    assert model == "llama3.1:8b"
    assert "not a reasoning model" in why


@pytest.mark.parametrize("action_id", ["transcript", "profile", "digest"])
def test_rare_free_text_jobs_prefer_the_stronger_model(action_id):
    model, why = llm_config.recommend(action_id, INSTALLED)
    assert model == "gpt-oss:20b"
    assert "reasons before answering" in why


def test_a_reasoning_only_server_is_called_out_rather_than_endorsed(db_conn):
    """Recommending the least-bad option without saying so would be misleading."""
    model, why = llm_config.recommend("scoring", ["gpt-oss:20b", "deepseek-r1:8b"])
    assert model in ("gpt-oss:20b", "deepseek-r1:8b")
    assert "poor fit" in why and "general instruct model" in why


def test_no_models_means_no_recommendation():
    model, why = llm_config.recommend("scoring", [])
    assert model is None and "did not report" in why


def test_a_stated_size_beats_an_unstated_one():
    """`llama3.2:latest` hides its size; guessing wrong is worse than caution."""
    model, _ = llm_config.recommend("scoring", ["llama3.2:latest", "mistral:7b"])
    assert model == "mistral:7b"


def test_current_reports_a_suboptimal_choice(db_conn):
    llm_config.set_model(db_conn, "scoring", "gpt-oss:20b")
    db_conn.commit()
    row = {r["action"].id: r for r in llm_config.current(db_conn, INSTALLED)}["scoring"]
    assert row["suboptimal"] is True
    assert row["suggested"] == "llama3.1:8b"


def test_a_merely_different_choice_is_not_flagged_as_bad(db_conn):
    """Preferring a smaller model is a judgement call, not a mistake."""
    llm_config.set_model(db_conn, "scoring", "llama3.2:latest")
    db_conn.commit()
    row = {r["action"].id: r for r in llm_config.current(db_conn, INSTALLED)}["scoring"]
    assert row["suboptimal"] is False


# ── the panel ──────────────────────────────────────────────────────────────────

@patch("app.routes.ollama_client.list_models", return_value=INSTALLED)
def test_the_panel_recommends_and_explains(mock_list, client):
    body = client.get("/settings/models").get_data(as_text=True)
    assert "recommended" in body
    assert "Reasoning models" in body            # the general guidance
    assert "not a reasoning model" in body       # a per-job reason


@patch("app.routes.ollama_client.list_models", return_value=INSTALLED)
def test_the_panel_warns_when_a_reasoning_model_is_used_for_json(mock_list, client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        llm_config.set_model(db, "scoring", "gpt-oss:20b")
        db.commit()
        db.close()
    body = client.get("/settings/models").get_data(as_text=True)
    assert "reasons before answering, which this" in body
    assert "action-suggestion-warn" in body


@patch("app.routes.ollama_client.list_models", return_value=INSTALLED)
def test_applying_every_recommendation(mock_list, client, app):
    r = client.post("/settings/models/recommended")
    assert r.status_code == 200
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        assert llm_config.model_for(db, "scoring") == "llama3.1:8b"
        assert llm_config.model_for(db, "digest") == "gpt-oss:20b"
        db.close()


@patch("app.routes.ollama_client.list_models", return_value=[])
def test_applying_recommendations_without_ollama_changes_nothing(mock_list, client, app):
    client.post("/settings/models/recommended")
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        assert all(r["inherited"] for r in llm_config.current(db))
        db.close()


def test_applying_recommendations_is_admin_only(login_as):
    c, _ = login_as()
    assert c.post("/settings/models/recommended").status_code == 403

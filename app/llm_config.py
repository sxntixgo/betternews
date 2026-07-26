"""Which model runs which job.

The app makes six distinct kinds of Ollama call, and they have genuinely
different requirements — scoring needs reliable JSON across a batch, summaries
need fluent prose in the article's language, transcript work is long-context.
One model for all of them is a compromise, so each is configurable.

Resolution order for every action: its own setting, then the legacy
`scoring_model`/`summary_model` (so existing installs keep working), then the
env default. Nothing here reaches for a model that was never chosen.
"""

from dataclasses import dataclass

from app.db import get_setting


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    description: str
    legacy_key: str          # setting used before per-action models existed
    json_output: bool        # needs structured output, so model choice matters more

    @property
    def setting_key(self) -> str:
        return f"model_{self.id}"


ACTIONS: tuple[Action, ...] = (
    Action(
        "scoring", "Relevance scoring",
        "Scores every new article 0–1 against your preference profile and tags "
        "it with topics. Runs on every article, in batches — the heaviest user "
        "of the model, and the one that most needs reliable JSON.",
        "scoring_model", True,
    ),
    Action(
        "summary", "Article summaries",
        "Writes the 2–3 sentence summary for articles above the threshold. "
        "Also does the clickbait headline rewrite when that is enabled — it is "
        "the same request, so both use this model.",
        "summary_model", False,
    ),
    Action(
        "transcript", "Video summaries",
        "Summarizes YouTube videos from their captions. Spoken text is long and "
        "unpunctuated, so a model with a larger context window helps here.",
        "summary_model", False,
    ),
    Action(
        "asides", "Padding detection",
        "Finds related-story rails and older-news recaps inside an article. "
        "Only runs when the LLM pass is enabled in Article padding.",
        "summary_model", True,
    ),
    Action(
        "profile", "Preference profile",
        "Rebuilds the profile that scoring uses, from your votes. Runs nightly "
        "and on demand — rare, so a slower, stronger model is affordable.",
        "summary_model", False,
    ),
    Action(
        "digest", "What you missed",
        "Writes the briefing that groups your unread articles into themes. "
        "Once per change to your unread list.",
        "summary_model", False,
    ),
)

BY_ID = {a.id: a for a in ACTIONS}


def model_for(db, action_id: str) -> str:
    """The model configured for an action, falling back rather than failing."""
    action = BY_ID[action_id]
    chosen = (get_setting(db, action.setting_key, "") or "").strip()
    if chosen:
        return chosen
    legacy = (get_setting(db, action.legacy_key, "") or "").strip()
    if legacy:
        return legacy
    from app.pipeline import DEFAULT_SCORING_MODEL, DEFAULT_SUMMARY_MODEL
    return DEFAULT_SCORING_MODEL if action_id == "scoring" else DEFAULT_SUMMARY_MODEL


def set_model(db, action_id: str, model: str) -> None:
    """Store a choice. An empty value clears it, reverting to the fallback."""
    if action_id not in BY_ID:
        raise ValueError(f"Unknown action: {action_id}")
    from app.db import set_setting
    set_setting(db, BY_ID[action_id].setting_key, (model or "").strip())


def current(db, installed: list[str] | None = None) -> list[dict]:
    """Every action with its resolved model, for the settings panel.

    `missing` is the case that matters: a model configured but not installed is
    exactly how scoring failed silently for six weeks.
    """
    installed = installed or []
    rows = []
    for action in ACTIONS:
        explicit = (get_setting(db, action.setting_key, "") or "").strip()
        resolved = model_for(db, action.id)
        rows.append({
            "action": action,
            "explicit": explicit,
            "model": resolved,
            "inherited": not explicit,
            "missing": bool(installed) and resolved not in installed,
        })
    return rows

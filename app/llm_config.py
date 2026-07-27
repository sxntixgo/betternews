"""Which model runs which job.

The app makes six distinct kinds of Ollama call, and they have genuinely
different requirements — scoring needs reliable JSON across a batch, summaries
need fluent prose in the article's language, transcript work is long-context.
One model for all of them is a compromise, so each is configurable.

Resolution order for every action: its own setting, then the legacy
`scoring_model`/`summary_model` (so existing installs keep working), then the
env default. Nothing here reaches for a model that was never chosen.
"""

import re
from dataclasses import dataclass

from app.db import get_setting

# Families that reason before answering. They are a poor fit for the structured,
# per-article jobs -- they spend their output budget thinking and often never
# reach the JSON -- and a good fit for the rare, free-text ones.
_REASONING_HINTS = ("gpt-oss", "deepseek-r1", "qwq", "magistral", "marco-o1",
                    "reasoning", "thinking", "-r1:", "phi4-reasoning")

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.IGNORECASE)


def is_reasoning_model(name: str) -> bool:
    n = (name or "").lower()
    return any(h in n for h in _REASONING_HINTS)


def model_size_b(name: str) -> float | None:
    """Parameter count from the tag, when it says. `llama3.2:latest` does not."""
    m = _SIZE_RE.search(name or "")
    return float(m.group(1)) if m else None


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    description: str
    legacy_key: str          # setting used before per-action models existed
    json_output: bool        # needs structured output, so model choice matters more
    heavy: bool              # runs per article, so speed compounds
    guidance: str            # what to look for, and why
    ideal_b: float           # parameter count that suits this job

    @property
    def setting_key(self) -> str:
        return f"model_{self.id}"

    @property
    def avoid_reasoning(self) -> bool:
        """Reasoning costs output budget. That is fatal for structured output
        and expensive when it runs on every article."""
        return self.json_output or self.heavy


ACTIONS: tuple[Action, ...] = (
    Action(
        "scoring", "Relevance scoring",
        "Scores every new article 0–1 against your preference profile and tags "
        "it with topics. Runs on every article, in batches — the heaviest user "
        "of the model, and the one that most needs reliable JSON.",
        "scoring_model", True, True,
        "Needs dependable JSON on every article, so favour a mid-size "
        "general model and avoid reasoning models -- they spend their output "
        "budget thinking and often never reach the JSON.",
        8,
    ),
    Action(
        "summary", "Article summaries",
        "Writes the 2–3 sentence summary for articles above the threshold. "
        "Also does the clickbait headline rewrite when that is enabled — it is "
        "the same request, so both use this model.",
        "summary_model", False, True,
        "Runs on every article that clears the threshold, so speed compounds. "
        "A mid-size model writes fluent prose fast; going bigger costs more "
        "than it adds here.",
        8,
    ),
    Action(
        "transcript", "Video summaries",
        "Summarizes YouTube videos from their captions. Captions are rambling "
        "and unpunctuated, and working out what a video was actually about is a "
        "synthesis problem. Runs once per video.",
        "summary_model", False, False,
        "Free text and infrequent, so a stronger or reasoning model is "
        "affordable here and handles rambling speech better. Transcripts are "
        "truncated before sending, so context size is not the constraint.",
        14,
    ),
    Action(
        "asides", "Padding detection",
        "Finds related-story rails and older-news recaps inside an article. "
        "Only runs when the LLM pass is enabled in Article padding.",
        "summary_model", True, True,
        "Structured output on every summarized article. Same as scoring: "
        "mid-size, and not a reasoning model.",
        8,
    ),
    Action(
        "profile", "Preference profile",
        "Rebuilds the profile that scoring uses, from your votes. Runs nightly "
        "and on demand, so a slower, stronger model is affordable.",
        "summary_model", False, False,
        "Runs nightly. This one shapes every future score, so it is the best "
        "place to spend on a stronger or reasoning model.",
        14,
    ),
    Action(
        "digest", "What you missed",
        "Writes the briefing that groups your unread articles into themes. "
        "Once per change to your unread list.",
        "summary_model", False, False,
        "Grouping loosely-related articles into themes rewards a stronger "
        "model, and it runs rarely enough that speed hardly matters.",
        14,
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


def recommend(action_id: str, installed: list[str]) -> tuple[str | None, str]:
    """Pick the best installed model for a job, and say why.

    Deliberately heuristic and transparent: it ranks what is actually on the
    server rather than naming models you may not have. A tag that omits its
    parameter count (`llama3.2:latest`) is treated as unknown size and ranked
    below one that states it, since guessing wrong is worse than being cautious.
    """
    action = BY_ID[action_id]
    if not installed:
        return None, "Ollama did not report any installed models."

    scored = []
    for name in installed:
        reasoning = is_reasoning_model(name)
        size = model_size_b(name)
        if action.avoid_reasoning and reasoning:
            # Not merely worse -- this is the failure that produces empty
            # responses and truncated JSON.
            penalty = 100.0
        elif not action.avoid_reasoning and reasoning:
            penalty = -3.0            # a positive for the rare, free-text jobs
        else:
            penalty = 0.0
        distance = abs((size if size is not None else 3.0) - action.ideal_b)
        if size is None:
            distance += 2.0           # unstated size is a mild unknown
        scored.append((distance + penalty, name, reasoning, size))

    scored.sort()
    best_score, best, reasoning, size = scored[0]
    if best_score >= 100:
        return best, ("Every installed model reasons before answering, which is "
                      "a poor fit for this job. A general instruct model would "
                      "be more reliable here.")

    bits = []
    if size:
        bits.append(f"{size:g}B")
    if reasoning:
        bits.append("reasons before answering, which suits this job")
    elif action.avoid_reasoning:
        bits.append("not a reasoning model")
    why = f"Best fit installed: {', '.join(bits)}." if bits else "Best fit installed."
    return best, why


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
        suggested, why = recommend(action.id, installed)
        rows.append({
            "action": action,
            "explicit": explicit,
            "model": resolved,
            "inherited": not explicit,
            "missing": bool(installed) and resolved not in installed,
            "suggested": suggested,
            "suggested_why": why,
            # Only nag when the current choice is actually a poor one.
            "suboptimal": bool(
                installed and suggested and resolved != suggested
                and action.avoid_reasoning and is_reasoning_model(resolved)
            ),
        })
    return rows

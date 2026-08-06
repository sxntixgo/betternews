"""The parts of the prompts a reader may edit, and the parts they may not.

Prompts are templates, not prose. `scoring_prompt` interpolates six things --
`{title}`, `{safe_snippet}`, `{profile_section}`, `{vocab_block}`,
`{SCORING_RULES}`, `{KIND_BLOCK}` -- and dropping one does not raise. It
produces a prompt that still looks reasonable, still returns a confident score,
and no longer contains the article. That is the silent-failure shape this
codebase keeps having to dig out of, so free-text editing of the whole prompt is
not on offer.

What *is* on offer is every part that encodes an opinion rather than a contract:

    scoring_rules     how subject weighs against style
    kinds             the nine story kinds and what each one means
    tag_range         how many topics to ask for
    profile_framing   what the profile should describe

The rest -- the JSON shape the parser depends on, the `<article_snippet>`
delimiters that stop a hostile feed injecting instructions into the scorer --
stays fixed. `validate` proves that by rendering the real prompts with the
override applied and checking the invariants survived, so a slot cannot break
something at a distance.
"""

from app import kinds as kinds_mod
from app.db import get_setting, set_setting

PREFIX = "prompt_"

# Everything a rendered scoring prompt must still contain, whatever has been
# edited. The first two are a security boundary and the third is the parser
# contract; all three have been broken by accident before in one form or another.
INVARIANTS = (
    ("<article", "the delimiter that marks feed text as data, not instructions"),
    ("raw text data only", "the instruction not to follow what a feed says"),
    ('"score"', "the JSON shape the scorer is parsed with"),
)

MAX_CHARS = 4000


def _default_kinds() -> str:
    return "\n".join(f"{k} — {d}" for k, d in kinds_mod.KINDS)


def _default_scoring_rules() -> str:
    from app import prompts
    return prompts.DEFAULT_SCORING_RULES


def _default_profile_framing() -> str:
    from app import prompts
    return prompts.DEFAULT_PROFILE_FRAMING


SLOTS: dict[str, dict] = {
    "scoring_rules": {
        "label": "How relevance is judged",
        "help": ("Subject against style. The default exists because the scorer "
                 "was giving 0.00 to a tournament named in the reader's own "
                 "profile, calling it \"no tactical depth\"."),
        "default": _default_scoring_rules,
    },
    "kinds": {
        "label": "Story kinds",
        "help": ("One per line, `slug — what it means`. The last line is the "
                 "fallback for anything that fits nothing else. Keep the list "
                 "short and the slugs stable: affinity is learned per kind, so "
                 "renaming one discards what was learned about it."),
        "default": _default_kinds,
    },
    "tag_range": {
        "label": "How many topics to ask for",
        "help": ("Measured: affinity predicts at AUC 0.657 on a one-tag "
                 "article, 0.752 on two, 0.780 on three or four. More is "
                 "better until the model starts inventing them."),
        "default": lambda: "4-8",
    },
    "profile_framing": {
        "label": "What the profile should describe",
        "help": ("Subjects, not style. Asking for \"writing style or depth\" "
                 "is what produced a profile claiming this reader valued crime "
                 "and health stories, which they reject at 23% and 16%."),
        "default": _default_profile_framing,
    },
}


def load(db) -> dict[str, str]:
    """Every slot, override or default. Never partial: callers interpolate all."""
    out = {}
    for slot, spec in SLOTS.items():
        stored = (get_setting(db, PREFIX + slot, "") or "").strip()
        out[slot] = stored or spec["default"]()
    return out


def is_default(db, slot: str) -> bool:
    return not (get_setting(db, PREFIX + slot, "") or "").strip()


def parse_kinds(text: str) -> list[tuple[str, str]]:
    """`slug — description` per line, tolerant about which dash."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for sep in ("—", " - ", "–", ":"):
            if sep in line:
                slug, desc = line.split(sep, 1)
                break
        else:
            slug, desc = line, ""
        slug = slug.strip().lower().replace(" ", "-").replace("_", "-")
        if slug:
            out.append((slug, desc.strip()))
    return out


def parse_tag_range(text: str) -> tuple[int, int] | None:
    parts = text.replace("–", "-").split("-")
    if len(parts) != 2:
        return None
    try:
        lo, hi = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None
    return (lo, hi) if 1 <= lo < hi <= 12 else None


def validate(db, slot: str, text: str) -> str | None:
    """The reason this edit is refused, or None.

    Ends by rendering the real prompts with the override applied and checking
    the invariants survived -- a slot is interpolated into a template, so the
    only honest way to know it did no damage is to build the thing and look.
    """
    if slot not in SLOTS:
        return f"Unknown prompt setting: {slot}"
    text = (text or "").strip()
    if not text:
        return None                      # empty clears the override
    if len(text) > MAX_CHARS:
        return f"Too long: {len(text)} characters, limit is {MAX_CHARS}."

    if slot == "kinds":
        parsed = parse_kinds(text)
        if len(parsed) < 2:
            return "Give at least two kinds, one per line."
        bad = [s for s, _ in parsed if not s.replace("-", "").isalnum()]
        if bad:
            return f"These are not usable slugs: {', '.join(bad[:3])}"
        if len(parsed) != len({s for s, _ in parsed}):
            return "The same slug appears twice."
        if any(not d for _, d in parsed):
            return "Every kind needs a description after the dash."

    if slot == "tag_range" and parse_tag_range(text) is None:
        return "Give a range like 4-8, low first, both between 1 and 12."

    # Build the real prompts with this override in place.
    from app import prompts
    over = load(db)
    over[slot] = text
    rendered = [
        prompts.scoring_prompt("profile", "title", "snippet", overrides=over),
        prompts.batch_scoring_prompt(
            "profile", [{"id": 1, "title": "t", "snippet": "s"}], overrides=over),
    ]
    for token, why in INVARIANTS:
        for text_out in rendered:
            if token not in text_out:
                return f"That edit removes {why}."
    return None


def save(db, slot: str, text: str) -> str | None:
    """Store it, or return why not. Empty text resets to the default."""
    problem = validate(db, slot, text)
    if problem:
        return problem
    set_setting(db, PREFIX + slot, (text or "").strip())
    return None

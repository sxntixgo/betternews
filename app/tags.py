"""Feed tags: the canonical form, and how to read it back.

`feeds.tags` is a comma-separated Text column, not an array. That is worth
knowing before calling `list()` on it, which iterates characters -- exactly what
the first version of the API serializer did.

Lives outside `app/views/` because both the JSON API and (while it existed) the
HTML form had to produce the same tag from the same typing. Two copies would
have made "Tech" and "tech" two different sidebar groups.
"""


def normalize(raw: str) -> str:
    """A free-form tags string in canonical form.

    Splits on commas, trims, lowercases, drops empties, dedupes, sorts. Returns
    '' for input that produces no tags, which the caller stores as NULL.
    """
    if not raw:
        return ""
    seen: list[str] = []
    for part in raw.split(","):
        t = part.strip().lower()
        if t and t not in seen:
            seen.append(t)
    seen.sort()
    return ",".join(seen)


def split(raw: str | None) -> list[str]:
    """The stored string back as a list. Empty for NULL or ''."""
    if not raw:
        return []
    return [p for p in raw.split(",") if p]

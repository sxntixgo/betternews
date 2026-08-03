"""The presenter layer must stay usable by a client that is not a browser.

These tests are about the *shape* of the module, not its behaviour — the
behaviour tests live in test_routes.py, where they were written, and were left
alone on purpose so the extraction stayed a pure move.
"""

import ast
import inspect
import pathlib

import pytest

from app import presenters

SOURCE = pathlib.Path(inspect.getfile(presenters)).read_text()
TREE = ast.parse(SOURCE)

# What a request context provides. A phone has none of it.
FLASK_GLOBALS = {"request", "g", "session", "current_app", "render_template",
                 "url_for", "Response", "redirect", "abort", "flash", "jsonify"}


def test_presenters_does_not_import_flask():
    """Checked structurally: the word "request" appears in the docstring."""
    imported = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "flask" not in imported, f"presenters imports flask; imports={sorted(imported)}"


@pytest.mark.parametrize("fn", [
    n.name for n in ast.walk(ast.parse(SOURCE))
    if isinstance(n, ast.FunctionDef)
])
def test_no_presenter_reaches_for_a_request_context(fn):
    node = next(n for n in ast.walk(TREE)
                if isinstance(n, ast.FunctionDef) and n.name == fn)
    used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    used |= {n.value.id for n in ast.walk(node)
             if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    leaked = sorted(used & FLASK_GLOBALS)
    assert not leaked, f"{fn}() depends on {leaked}; a mobile client has none of it"


def test_settings_arrive_as_an_argument():
    """The two presenters that read settings take `db`, rather than reaching for
    it. That is what makes them callable from a worker or a serializer."""
    for name in ("declickbait", "content_filter_mode"):
        params = list(inspect.signature(getattr(presenters, name)).parameters)
        assert params[0] == "db", f"{name}{tuple(params)} should take db first"


def test_the_layer_is_importable_without_an_app():
    """No app context, no request, no Flask -- just call it.

    This is the whole point of the module: the same decisions, reachable from
    any client. If this ever needs a fixture, the seam has leaked.
    """
    row = {"title": "Real headline", "clean_title": "Clickbait!",
           "title_was_clickbait": True, "raw_snippet": "8 min read",
           "full_text_head": ""}
    article = presenters.row_to_article(row, declickbait=True)
    assert article["display_title"] == "Clickbait!"
    assert article["original_title"] == "Real headline"
    assert article["reading_time"] == "8"

    off = presenters.row_to_article(row, declickbait=False)
    assert off["display_title"] == "Real headline"
    assert off["original_title"] is None


# ── moved from tests/test_routes.py ───────────────────────────────────────────
# These test pure functions in `app/presenters.py` and `app/tags.py`. They lived
# beside the HTML route tests because that is where the functions used to be;
# the routes are gone and the functions are not, so they moved rather than went.
def test_extract_reading_time_english():
    from app.presenters import extract_reading_time
    assert extract_reading_time("This article is 7 min read.") == "7"


def test_extract_reading_time_spanish():
    from app.presenters import extract_reading_time
    assert extract_reading_time("- 4 minutos de lectura") == "4"


def test_extract_reading_time_none():
    from app.presenters import extract_reading_time
    assert extract_reading_time("no reading time here") is None


def test_clean_content_strips_reading_time():
    from app.presenters import clean_content
    text = (
        "Real first paragraph " * 20 + "\n"
        "- 4 minutos de lectura\n"
        "Otras noticias\n"
    )
    out = clean_content(text, title="Real first paragraph")
    assert "lectura" not in out.lower()
    # Junk is no longer deleted here — content_filter classifies it instead, so
    # the reader can fold it recoverably rather than truncating the body.
    assert "Otras noticias" in out


def test_clean_content_skips_duplicate_title_line():
    from app.presenters import clean_content
    out = clean_content("Some Title\nFirst paragraph.", title="Some Title")
    assert out.startswith("First paragraph")


def test_clean_content_skips_duplicate_description_line():
    from app.presenters import clean_content
    desc = "This is the description that leads the article and should not repeat."
    out = clean_content(desc + "\nReal body line.", description=desc)
    assert out.startswith("Real body line")


def test_clean_content_keeps_pagination_for_the_filter_to_classify():
    from app.presenters import clean_content
    body = ("Real first paragraph " * 30).strip() + "\n- 1\nrelated thing"
    out = clean_content(body)
    assert "- 1" in out
    assert "related thing" in out


def test_to_blocks_groups_consecutive_dash_bullets():
    from app.presenters import to_blocks
    text = "Intro paragraph.\n- first\n- second\n- third\nClosing line."
    blocks = to_blocks(text)
    assert blocks[0] == {"type": "p", "text": "Intro paragraph."}
    assert blocks[1] == {"type": "ul", "items": ["first", "second", "third"]}
    assert blocks[2] == {"type": "p", "text": "Closing line."}


def test_to_blocks_supports_star_and_unicode_bullets():
    from app.presenters import to_blocks
    blocks = to_blocks("* alpha\n• beta\n– gamma\nplain")
    assert blocks[0]["type"] == "ul"
    assert blocks[0]["items"] == ["alpha", "beta", "gamma"]
    assert blocks[1] == {"type": "p", "text": "plain"}


def test_to_blocks_separate_bullet_groups():
    from app.presenters import to_blocks
    blocks = to_blocks("- a\n- b\nbreak\n- c")
    assert [b["type"] for b in blocks] == ["ul", "p", "ul"]
    assert blocks[0]["items"] == ["a", "b"]
    assert blocks[2]["items"] == ["c"]


def test_to_blocks_ignores_empty_input():
    from app.presenters import to_blocks
    assert to_blocks("") == []


def test_to_blocks_emits_twitter_embed_when_enabled():
    from app.presenters import to_blocks
    text = "Setup line.\nhttps://twitter.com/jack/status/20\nFollow-up."
    blocks = to_blocks(text, embeds_enabled=True)
    assert blocks[1] == {
        "type": "embed",
        "platform": "twitter",
        "url": "https://twitter.com/jack/status/20",
    }


def test_to_blocks_recognises_x_com_and_instagram():
    from app.presenters import to_blocks
    text = (
        "https://x.com/elon/status/1234567890\n"
        "https://www.instagram.com/p/AbCdEf-12_/\n"
        "https://www.instagram.com/reel/XyZ123/"
    )
    blocks = to_blocks(text, embeds_enabled=True)
    assert [b["platform"] for b in blocks] == ["twitter", "instagram", "instagram"]
    assert all(b["type"] == "embed" for b in blocks)


def test_to_blocks_embed_disabled_keeps_url_as_paragraph():
    from app.presenters import to_blocks
    url = "https://twitter.com/jack/status/20"
    blocks = to_blocks(url)
    assert blocks == [{"type": "p", "text": url}]


def test_to_blocks_inline_url_is_not_an_embed():
    from app.presenters import to_blocks
    text = "Check https://twitter.com/jack/status/20 — interesting."
    blocks = to_blocks(text, embeds_enabled=True)
    assert blocks[0]["type"] == "p"
    assert "twitter.com" in blocks[0]["text"]


def test_to_blocks_embed_breaks_running_bullet_list():
    from app.presenters import to_blocks
    text = "- one\n- two\nhttps://twitter.com/u/status/9\n- three"
    blocks = to_blocks(text, embeds_enabled=True)
    assert [b["type"] for b in blocks] == ["ul", "embed", "ul"]
    assert blocks[0]["items"] == ["one", "two"]
    assert blocks[2]["items"] == ["three"]


def test_normalize_tags_lowercases_trims_dedupes_sorts():
    from app.tags import normalize as _normalize_tags
    assert _normalize_tags("") == ""
    assert _normalize_tags(None) == ""
    assert _normalize_tags("Tech") == "tech"
    assert _normalize_tags("  tech , News  ") == "news,tech"
    assert _normalize_tags("tech,tech,news,Tech") == "news,tech"
    assert _normalize_tags(",,,") == ""


def test_split_tags_handles_empty_and_missing():
    from app.tags import split as _split_tags
    assert _split_tags(None) == []
    assert _split_tags("") == []
    assert _split_tags("tech,news") == ["tech", "news"]


def test_group_blocks_merges_runs():
    from app.presenters import group_blocks
    groups = group_blocks([
        {"type": "p", "text": "a"},
        {"type": "p", "text": "b", "aside": "promo"},
        {"type": "p", "text": "c", "aside": "promo"},
        {"type": "p", "text": "d"},
    ])
    assert [g["aside"] for g in groups] == [None, "promo", None]
    assert len(groups[1]["blocks"]) == 2
    assert groups[1]["label"] == "Related links" or groups[1]["label"] == "Promotion"


def test_bullet_run_splits_when_a_rail_starts_mid_list():
    """A rail heading inside a list must not drag the real items in with it."""
    from app.presenters import to_blocks
    from app import content_filter as cf
    lines = ["- real one", "- real two", "Related", "- other story"]
    kinds = cf.classify_lines(lines)
    blocks = to_blocks("\n".join(lines), aside_kinds=kinds)
    uls = [b for b in blocks if b["type"] == "ul"]
    assert len(uls) == 2
    assert uls[0]["items"] == ["real one", "real two"]
    assert "aside" not in uls[0]
    assert uls[1]["items"] == ["other story"]
    assert uls[1]["aside"] == cf.KIND_RELATED


# ── branches the HTML route tests used to cover ───────────────────────────────

def test_an_embed_inside_an_aside_keeps_the_aside_marking():
    """A tweet quoted inside a related-links rail is still part of the rail.
    Losing the marking would leave it stranded outside the fold."""
    from app.presenters import to_blocks
    blocks = to_blocks("https://twitter.com/x/status/1", embeds_enabled=True,
                       aside_kinds=["related_links"])
    assert blocks == [{"type": "embed", "platform": "twitter",
                       "url": "https://twitter.com/x/status/1",
                       "aside": "related_links"}]


def test_padding_mode_off_renders_the_body_whole():
    from app import content_filter
    from app.presenters import content_blocks
    groups, asides = content_blocks(
        "The reporting.\nRelated stories\nSomething else.",
        embeds_enabled=False, mode=content_filter.MODE_OFF, stored_asides=None)
    assert asides == 0, "nothing is classified in off mode"
    texts = [b["text"] for g in groups for b in g["blocks"]]
    assert "Related stories" in texts, "nothing is folded away"


def test_resolve_title_falls_back_in_every_unusable_case():
    """`clean_title IS NULL` means never processed, so pre-feature articles must
    render unchanged. Every rejection degrades to the original."""
    from app.presenters import resolve_title
    original = "The real headline"
    for row in (
        {"title": original, "clean_title": None, "title_was_clickbait": True},
        {"title": original, "clean_title": "   ", "title_was_clickbait": True},
        {"title": original, "clean_title": "Rewritten", "title_was_clickbait": False},
        {"title": original, "clean_title": original, "title_was_clickbait": True},
    ):
        assert resolve_title(row, declickbait=True) == (original, None)
    assert resolve_title(
        {"title": original, "clean_title": "Rewritten", "title_was_clickbait": True},
        declickbait=True) == ("Rewritten", original)

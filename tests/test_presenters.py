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

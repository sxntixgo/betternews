"""Which parts of a prompt a reader may edit, and what stops them breaking it.

Prompts are templates: `scoring_prompt` interpolates six values and dropping
one does not raise. It renders a prompt that still looks reasonable, still
returns a confident score, and no longer contains the article. So the opinions
are editable, the contracts are not, and every save is checked by building the
real prompts and looking for the invariants.
"""

import pytest

from app import prompt_overrides as po


def test_every_slot_falls_back_to_its_default(db_conn):
    loaded = po.load(db_conn)
    assert set(loaded) == set(po.SLOTS)
    for slot, spec in po.SLOTS.items():
        assert loaded[slot] == spec["default"]()
        assert po.is_default(db_conn, slot)


def test_saving_and_clearing(db_conn):
    assert po.save(db_conn, "tag_range", "3-5") is None
    assert po.load(db_conn)["tag_range"] == "3-5"
    assert not po.is_default(db_conn, "tag_range")
    # Empty resets rather than blanking: there is no way to end up with none.
    assert po.save(db_conn, "tag_range", "") is None
    assert po.load(db_conn)["tag_range"] == "4-8"
    assert po.is_default(db_conn, "tag_range")


def test_an_unknown_slot_is_refused(db_conn):
    assert "Unknown prompt setting" in po.validate(db_conn, "everything", "x")


def test_a_wall_of_text_is_refused(db_conn):
    problem = po.validate(db_conn, "scoring_rules", "x" * (po.MAX_CHARS + 1))
    assert "Too long" in problem


@pytest.mark.parametrize("value,fragment", [
    ("one — only one line", "at least two"),
    ("a — first\na — again", "twice"),
    ("no-dash-here\nb — second", "description"),
    ("!!! — punctuation\nb — second", "not usable slugs"),
])
def test_a_broken_kind_list_is_refused(db_conn, value, fragment):
    assert fragment in po.validate(db_conn, "kinds", value)


@pytest.mark.parametrize("value", [
    "9-2",       # backwards
    "banana",    # no separator at all
    "few-many",  # separator, but neither side is a number
    "1-99",      # out of range
    "4",         # only one number
    "4-5-6",     # three
])
def test_a_broken_tag_range_is_refused(db_conn, value):
    assert po.validate(db_conn, "tag_range", value) is not None


@pytest.mark.parametrize("raw,expected", [
    ("4-8", (4, 8)),
    (" 3 - 5 ", (3, 5)),
    ("3–5", (3, 5)),          # en dash, which is what a Mac types
])
def test_tag_ranges_that_should_parse(raw, expected):
    assert po.parse_tag_range(raw) == expected


@pytest.mark.parametrize("line,slug", [
    ("fixture — when to watch", "fixture"),
    ("Match Report - what happened", "match-report"),
    ("transfer: signings", "transfer"),
    ("live – minute by minute", "live"),
])
def test_kind_lines_parse_whichever_dash_was_typed(line, slug):
    assert po.parse_kinds(line)[0][0] == slug


def test_blank_lines_in_a_kind_list_are_skipped():
    assert len(po.parse_kinds("a — one\n\n  \nb — two")) == 2


def test_an_edit_that_removes_an_invariant_is_refused(db_conn, monkeypatch):
    """The check renders the real prompts rather than trusting that a slot only
    affects itself. Faked here by demanding a token no prompt contains, since
    none of the real slots *can* remove one -- which is the point."""
    monkeypatch.setattr(po, "INVARIANTS",
                        (("NEVER-PRESENT", "the thing that must survive"),))
    problem = po.validate(db_conn, "scoring_rules", "- Anything at all.")
    assert problem == "That edit removes the thing that must survive."


def test_save_refuses_without_writing(db_conn):
    po.save(db_conn, "tag_range", "3-5")
    assert po.save(db_conn, "tag_range", "nonsense") is not None
    # The bad edit must not have replaced the good one.
    assert po.load(db_conn)["tag_range"] == "3-5"

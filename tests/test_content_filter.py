import json

import pytest

from app import content_filter as cf


# ── Pass 1: deterministic classification ───────────────────────────────────────

@pytest.mark.parametrize("heading", [
    "Related stories", "More from The Verge", "See also",
    "Read next", "Recommended", "You might also like",
    "Otras noticias", "Más noticias", "Noticias relacionadas",
    "Te puede interesar", "También te puede interesar", "Sigue leyendo",
])
def test_section_heading_starts_a_tail_aside(heading):
    kinds = cf.classify_lines(["Real body.", heading, "Some other headline"])
    assert kinds[0] is None
    assert kinds[1] == cf.KIND_RELATED
    # Rails run to the end of the body, so everything after is padding too.
    assert kinds[2] == cf.KIND_RELATED


def test_body_before_a_rail_is_untouched():
    lines = ["First para.", "Second para.", "Related", "Other story"]
    assert cf.classify_lines(lines) == [None, None, cf.KIND_RELATED, cf.KIND_RELATED]


def test_ordinary_article_has_no_asides():
    lines = ["The council met on Tuesday.", "It approved the budget.",
             "The vote was 7-2."]
    assert cf.classify_lines(lines) == [None, None, None]


def test_pagination_marker_only_counts_late_in_the_body():
    early = cf.classify_lines(["- 1", "Body text here."])
    assert early[0] is None          # a real list item near the top
    long_body = ["word " * 100, "- 1", "trailing"]
    late = cf.classify_lines(long_body)
    assert late[1] == cf.KIND_RELATED
    assert late[2] == cf.KIND_RELATED


@pytest.mark.parametrize("line", [
    "This article was originally published on Example.com",
    "Este artículo fue publicado originalmente en Example",
    "Sign up for the daily briefing",
    "Subscribe to our newsletter",
    "Advertisement",
    "Sponsored",
    "Follow us on Twitter",
    "Copyright 2026 Example Media",
    "All rights reserved",
])
def test_promo_lines_are_marked_individually(line):
    """Promos appear mid-article; treating one as a section boundary would
    discard every paragraph after it."""
    kinds = cf.classify_lines(["Body.", line, "More body."])
    assert kinds[1] == cf.KIND_PROMO
    assert kinds[2] is None


def test_bare_url_line_is_related():
    kinds = cf.classify_lines(["Body.", "https://example.com/other-story"])
    assert kinds[1] == cf.KIND_RELATED


def test_classify_handles_empty_input():
    assert cf.classify_lines([]) == []


# ── Fingerprints ───────────────────────────────────────────────────────────────

def test_fingerprint_is_stable_across_whitespace_and_case():
    assert cf.fingerprint("Hello   World") == cf.fingerprint("hello world")
    assert cf.fingerprint("  Hello World  ") == cf.fingerprint("Hello World")


def test_fingerprint_differs_for_different_text():
    assert cf.fingerprint("one") != cf.fingerprint("two")


# ── Stored LLM spans ───────────────────────────────────────────────────────────

def test_stored_spans_mark_matching_paragraphs():
    para = "Last month the mayor resigned after a separate scandal."
    stored = {cf.fingerprint(para): cf.KIND_OLDER}
    kinds = cf.classify_lines(["Today's news.", para, "More of today."], stored)
    assert kinds == [None, cf.KIND_OLDER, None]


def test_stored_spans_survive_whitespace_drift():
    stored = {cf.fingerprint("A recap paragraph."): cf.KIND_OLDER}
    kinds = cf.classify_lines(["Body.", "A   recap    paragraph."], stored)
    assert kinds[1] == cf.KIND_OLDER


@pytest.mark.parametrize("raw", [
    None, "", "not json", "[]", "{}", '"a string"',
    '[{"kind":"older_news"}]',          # no fingerprint
    '[{"h":"abc"}]',                    # no kind
    '[{"h":"abc","kind":"nonsense"}]',  # unknown kind
])
def test_load_stored_never_raises_on_bad_data(raw):
    assert cf.load_stored(raw) == {}


def test_load_stored_round_trips_dump_spans():
    raw = cf.dump_spans([("abc123", cf.KIND_OLDER), ("def456", cf.KIND_PROMO)])
    assert cf.load_stored(raw) == {"abc123": cf.KIND_OLDER, "def456": cf.KIND_PROMO}


def test_dump_spans_empty_is_none():
    assert cf.dump_spans([]) is None


# ── LLM response parsing ───────────────────────────────────────────────────────

def test_spans_from_llm_maps_indices_to_fingerprints():
    paras = ["zero", "one", "two"]
    result = {"asides": [{"index": 1, "kind": "older_news"}]}
    assert cf.spans_from_llm(result, paras) == [(cf.fingerprint("one"), cf.KIND_OLDER)]


@pytest.mark.parametrize("result", [
    {}, {"asides": "nope"}, {"asides": [None]}, {"asides": [{}]},
    {"asides": [{"index": "x"}]},
    {"asides": [{"index": 99}]},       # out of range
    {"asides": [{"index": -1}]},       # negative
])
def test_spans_from_llm_drops_bad_rows(result):
    assert cf.spans_from_llm(result, ["a", "b"]) == []


def test_spans_from_llm_defaults_unknown_kind_to_older_news():
    out = cf.spans_from_llm({"asides": [{"index": 0, "kind": "weird"}]}, ["a"])
    assert out == [(cf.fingerprint("a"), cf.KIND_OLDER)]


def test_spans_from_llm_deduplicates():
    out = cf.spans_from_llm(
        {"asides": [{"index": 0, "kind": "promo"}, {"index": 0, "kind": "promo"}]},
        ["a"],
    )
    assert len(out) == 1


def test_spans_from_llm_survives_partially_bad_response():
    """One malformed row must not discard the valid ones."""
    result = {"asides": [{"index": 0, "kind": "promo"}, "garbage", {"index": 99}]}
    assert cf.spans_from_llm(result, ["a", "b"]) == [(cf.fingerprint("a"), cf.KIND_PROMO)]

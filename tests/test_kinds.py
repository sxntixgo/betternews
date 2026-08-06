"""The second tagging axis: what kind of story, not what it is about.

`boca-juniors` is 28 likes and 30 dislikes in the owner's history -- 48%,
indistinguishable from noise -- because it contains both fixture listings and
transfer news. Broadcast-listing pieces run a 12.5% like-rate against 39.4% for
everything else, so the axis exists and the subject was never it.
"""

import pytest

from app import kinds


def test_the_vocabulary_is_closed():
    """Open-ended kinds would fragment the way topics did -- there are 763 of
    those. "fixture", "schedule" and "tv-listing" for one shape of article
    would make the affinity for each of them useless."""
    assert kinds.normalize("fixture") == "fixture"
    assert kinds.normalize("tv-listing") == kinds.DEFAULT
    assert kinds.normalize("schedule") == kinds.DEFAULT


@pytest.mark.parametrize("raw,expected", [
    ("Fixture", "fixture"),
    ("  TRANSFER  ", "transfer"),
    ("match_report", "match-report"),
    ("match report", "match-report"),
    (None, "news"),
    (123, "news"),
    ("", "news"),
])
def test_normalize_is_forgiving_about_shape_but_not_about_membership(raw, expected):
    assert kinds.normalize(raw) == expected


def test_every_kind_is_described_for_the_tagger():
    block = kinds.prompt_block()
    for k in kinds.VALID:
        assert k in block, f"{k} has no description in the prompt"
    # The distinction the whole axis exists for.
    assert "A fixture list about Boca Juniors" in block


def test_news_is_the_fallback_and_is_listed_last():
    """The tagger takes the first that fits, so the catch-all must come last or
    it swallows everything."""
    assert kinds.KINDS[-1][0] == "news"
    assert kinds.DEFAULT == "news"

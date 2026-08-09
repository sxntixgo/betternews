"""The guard that keeps a Spanish headline Spanish.

The interesting cases are not "does it know Spanish" but the two ways this can
go wrong in production: a rewrite that quietly translates, and a detector so
eager it blocks good rewrites it could not actually read.
"""
import pytest

from app import language


@pytest.mark.parametrize("text,expected", [
    # Function words are the signal. Every one of these is a real headline
    # shape: proper nouns plus the grammar holding them together.
    ("El Gobierno anunció una nueva medida para los jubilados", "es"),
    ("La Justicia investiga a los responsables del fraude", "es"),
    ("The government announced a new measure for pensioners", "en"),
    ("What the minister said about the deal that was signed", "en"),

    # Orthography outranks counting: one n-tilde settles it, with no function
    # word in sight.
    ("Mañana", "es"),
    ("¿Qué pasó?", "es"),

    # Not enough to say. A headline that is two proper nouns and a number is
    # the common case here, and guessing at it is how good rewrites get
    # blocked.
    ("Boca 2 River 1", None),
    ("Messi", None),
    ("", None),
    ("   ", None),

    # One function word is a coin flip, so one is not enough: "en" is an
    # ordinary fragment inside English text and "the" turns up in Spanish
    # headlines quoting an English title.
    ("Nvidia the Blackwell launch", None),
])
def test_detect(text, expected):
    assert language.detect(text) == expected


def test_accent_does_not_override_clear_english():
    """An English headline that borrows an accented word stays English.

    `SPANISH_CHARS` is decisive only when the word counting does not disagree
    with it; otherwise "The café that was opened in the city" would be Spanish.
    """
    assert language.detect("The café that was opened in the city by the mayor") == "en"


@pytest.mark.parametrize("original,candidate,ok", [
    # The bug this exists for: the model was asked for Spanish and answered in
    # English, and the reader got an English headline over a Spanish article.
    ("Lo que dijo el ministro sobre la inflación te va a sorprender",
     "What the minister said about inflation will surprise you", False),
    ("The government announced a new measure for pensioners",
     "El Gobierno anunció una nueva medida para los jubilados", False),

    # A real de-clickbait rewrite in the right language still goes through --
    # this guard must not cost the feature it protects.
    ("Lo que dijo el ministro te va a sorprender",
     "El ministro dijo que la inflación bajará en marzo", True),
    ("You won't believe what the CEO said",
     "CEO says the company will not cut jobs this year", True),

    # Unsure about either side means no objection. This gates a candidate that
    # has already passed every other check, so silence has to mean yes.
    ("Boca 2 River 1", "Boca beat River at La Bombonera", True),
    ("El Gobierno anunció una nueva medida para los jubilados", "Messi", True),
    ("", "", True),
])
def test_same_language(original, candidate, ok):
    assert language.same_language(original, candidate) is ok


def test_pipeline_discards_a_translated_rewrite():
    """The guard is wired into the rejection chain, not just importable.

    Every other rejection in `_clean_title_from` returns (None, 0) so the
    display path falls back to the original title; this one has to behave the
    same way rather than raising or passing something through.
    """
    from app.pipeline import _clean_title_from

    original = "Lo que dijo el ministro sobre la inflación te va a sorprender"
    translated = {
        "was_clickbait": True,
        "clean_title": "What the minister said about inflation will surprise you",
    }
    assert _clean_title_from(translated, original) == (None, 0)

    kept = {
        "was_clickbait": True,
        "clean_title": "El ministro dijo que la inflación bajará en marzo",
    }
    assert _clean_title_from(kept, original) == (
        "El ministro dijo que la inflación bajará en marzo", 1)

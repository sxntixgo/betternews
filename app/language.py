"""Is this headline still in the language it started in?

The de-clickbait prompt has always said "write the title in the same language as
the article", and a small model ignores it often enough that Spanish articles
came back with English headlines. An instruction is a request; this is the
check. It sits beside the other rejections in `pipeline._clean_title_from`, all
of which degrade to showing the original title.

**Deliberately only Spanish vs English, and deliberately unsure by default.**
Those are the two languages in play here, a title is five to twelve words, and
the cost of the two mistakes is not symmetric: refusing a good rewrite loses a
tidier headline, while accepting a translated one shows the reader a headline
in a language they may not read. So `detect` answers `None` unless the evidence
is clear, and `same_language` only objects when it is confident about *both*
sides. Anything else is treated as "no reason to interfere".

A whole language library would be 10-100x the code and the wrong shape: those
are trained on paragraphs and are least reliable on exactly the short strings
this has to judge.
"""
import re

# Function words carry the signal in a short string: they are the words a
# headline cannot avoid and a translation always replaces. Content words are
# useless here -- proper nouns survive translation unchanged, which is most of
# what a headline is made of.
#
# Every ambiguous token is left out on purpose. "a" is an article in English
# and a preposition in Spanish; "no" is both; "son" is a Spanish verb and an
# English noun. Including them would buy a little sensitivity and cost the
# thing that matters more here, which is not being wrong.
SPANISH = frozenset("""
    de la el los las un una unos unas en y que por para con del al se su sus
    es son está están más como sobre entre desde hasta pero lo le les ya
    tras según cuando donde quien cual también sin muy fue ser han hay
""".split())

ENGLISH = frozenset("""
    the of in to and for with on at by from is are was were that this these
    those it its as but not he she they them has have had will would can
    could after before over under between during about into than then
""".split())

# ñ and the inverted marks appear in no English text at all. Accented vowels
# are near-conclusive too -- English borrows a handful (café, naïve) and a
# headline is unlikely to lean on them.
SPANISH_CHARS = re.compile(r"[ñÑ¿¡áéíóúÁÉÍÓÚ]")

_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)

# Two hits, and more than the other language. One function word is a coin
# flip: "the" turns up in Spanish headlines quoting an English title, and
# "en" is an ordinary English word inside a proper noun.
MIN_HITS = 2


def detect(text: str) -> str | None:
    """`"es"`, `"en"`, or `None` when the evidence does not support either."""
    if not text:
        return None

    words = [w.lower() for w in _WORDS.findall(text)]
    es = sum(1 for w in words if w in SPANISH)
    en = sum(1 for w in words if w in ENGLISH)

    # Orthography outranks word counting: a headline with an ñ in it is
    # Spanish whatever the function words say.
    if SPANISH_CHARS.search(text) and en <= es:
        return "es"

    if es >= MIN_HITS and es > en:
        return "es"
    if en >= MIN_HITS and en > es:
        return "en"
    return None


def same_language(original: str, candidate: str) -> bool:
    """True unless both are confidently identified and they disagree.

    The default is True. This gates a rewrite that has already passed every
    other check, so an undetectable pair -- two proper nouns and a number --
    should go through, not be blocked by a detector that had nothing to read.
    """
    a, b = detect(original), detect(candidate)
    return a is None or b is None or a == b

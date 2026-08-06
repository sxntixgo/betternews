"""What *kind* of story an article is, as opposed to what it is about.

The second tagging axis, and it exists because the first one could not answer a
real question. `boca-juniors` is 28 likes and 30 dislikes in the owner's
history -- 48%, indistinguishable from noise -- so topic affinity learns nothing
from it at all. Split by kind and it is not close:

    "A qué hora juega Boca vs. O'Higgins"          disliked
    "En qué canal pasan Boca vs. O'Higgins"        disliked
    "Por dónde pasan Boca vs. O'Higgins"           disliked
    "Cómo ver a Boca en DirecTV y DGO"             disliked
    "Próximo partido de Boca: cuándo juega"        disliked

    "Se acerca el cierre del libro de pases"       liked
    "Boca busca cancha: las cuatro opciones"       liked
    "Leandro Paredes respaldó a Tomás Aranda"      liked
    "Qué es Recoleta FC: el modesto club"          liked

Same subject, opposite value. Measured across every vote, broadcast-listing
pieces run a 12.5% like-rate against 39.4% for everything else.

**A closed set, deliberately.** Topics are open and there are now 763 of them,
which is right for subjects and wrong here: a kind is only useful if the same
article shape gets the same label every time, and a free-form tagger would
produce "fixture", "schedule", "match-preview" and "tv-listing" for one thing.
Eight buckets, each of which a reader could plausibly feel differently about.
"""

# Ordered roughly from most to least specific: the tagger is told to take the
# first that fits, so "match-report" beats the catch-all "news".
KINDS: tuple[tuple[str, str], ...] = (
    ("fixture",
     "when or where to watch: kick-off times, TV channels, streaming, "
     "line-ups announced before play, schedules, draw brackets"),
    ("live",
     "minute-by-minute or live-blog coverage of something still happening"),
    ("match-report",
     "what happened in a game or contest that has finished"),
    ("transfer",
     "signings, contracts, negotiations, squad moves and the rumours about them"),
    ("interview",
     "built around what someone said: quotes, a press conference, a statement"),
    ("analysis",
     "opinion, explainer, tactical breakdown, or an argument about what it means"),
    ("service",
     "practical instructions or numbers the reader would act on: prices, "
     "how to apply for something, lottery results, weather, horoscopes, recipes"),
    ("listicle",
     "a ranked or numbered list as the point of the article"),
    ("news",
     "a reported event, and the fallback when nothing above fits"),
)

VALID = frozenset(k for k, _ in KINDS)
DEFAULT = "news"


def normalize(raw) -> str:
    """One of `VALID`, always.

    Anything unrecognised becomes the default rather than being stored: an
    invented kind would sit in the affinity table forever with a sample size of
    one, which is exactly the fragmentation the closed set exists to prevent.
    """
    if not isinstance(raw, str):
        return DEFAULT
    slug = raw.strip().lower().replace("_", "-").replace(" ", "-")
    return slug if slug in VALID else DEFAULT


def prompt_block() -> str:
    """The vocabulary, for the scoring prompts."""
    lines = "\n".join(f"    {k} — {d}" for k, d in KINDS)
    return (
        "- kind: EXACTLY ONE of the following, describing the shape of the "
        "article rather than its subject. Take the first that fits:\n"
        f"{lines}\n"
        "  This is not the topic. A fixture list about Boca Juniors is "
        '"fixture"; a transfer story about Boca Juniors is "transfer". The '
        "reader may want one and not the other."
    )

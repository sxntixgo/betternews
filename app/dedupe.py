"""Cross-feed duplicate detection.

HN, The Verge and Ars all carry the same story; all three score well; the top
of the list becomes one story three times. No LLM involved — canonical URLs and
title fingerprints are enough, and they're free.

Clustering is deliberately conservative. A false cluster hides a real story
behind an unrelated one, which is worse than showing a duplicate.
"""

import hashlib
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

# Tracking parameters that never identify the article itself.
_JUNK_PARAMS = re.compile(
    r"^(utm_|fbclid$|gclid$|mc_[ce]id$|ref$|ref_src$|source$|cmpid$|"
    r"smid$|partner$|__twitter_impression$|s$|at_medium$|at_campaign$)",
    re.IGNORECASE,
)

# Words carrying no distinguishing signal in a headline.
_STOPWORDS = frozenset("""
a an the and or but of for to in on at by with from as is are was were be been
que de la el los las un una y en para por con del al se lo su es
""".split())

_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)

# Share of tokens two titles must have in common to be judged the same story.
SIMILARITY_THRESHOLD = 0.70
MIN_TOKENS = 4


def canonical_url(url: str) -> str:
    """Strip tracking noise so the same article shared twice collapses."""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = "&".join(
        f"{k}={v}" for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _JUNK_PARAMS.match(k)
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, query, ""))


def title_tokens(title: str) -> frozenset[str]:
    words = [w for w in _WORD_RE.split((title or "").lower()) if w]
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of significant title words."""
    ta, tb = title_tokens(a), title_tokens(b)
    if len(ta) < MIN_TOKENS or len(tb) < MIN_TOKENS:
        return 0.0
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


def url_key(url: str) -> str:
    return "u:" + hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def title_key(title: str) -> str:
    """Order-independent fingerprint, so reordered headlines still match."""
    toks = sorted(title_tokens(title))
    return "t:" + hashlib.sha1(" ".join(toks).encode("utf-8")).hexdigest()[:16]


def cluster_for(db, url: str, title: str, *, window_days: int = 3) -> str:
    """Find or mint the cluster id for an incoming article.

    Only looks at recent articles: the same headline six months apart is a
    different story, and it keeps the scan bounded.
    """
    from sqlalchemy import text

    ukey = url_key(url)
    row = db.execute(
        text("SELECT cluster_id FROM articles WHERE cluster_id = :k LIMIT 1"),
        {"k": ukey},
    ).scalar()
    if row:
        return ukey

    if len(title_tokens(title)) >= MIN_TOKENS:
        recent = db.execute(text(
            "SELECT title, cluster_id FROM articles "
            "WHERE created_at > now() - make_interval(days => :d) "
            "AND cluster_id IS NOT NULL LIMIT 500"), {"d": window_days}
        ).mappings().all()
        best, best_score = None, 0.0
        for cand in recent:
            score = similarity(title, cand["title"])
            if score > best_score:
                best, best_score = cand["cluster_id"], score
        if best and best_score >= SIMILARITY_THRESHOLD:
            return best

    return ukey

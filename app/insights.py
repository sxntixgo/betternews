"""Ranking accuracy, measured rather than guessed.

`docs/plan.md` set the goal "after ~2 weeks of voting, top-10 feels accurate
≥70% of the time" and nothing ever measured it. These are the queries that do.

All read-only, all pure SQL, no LLM.
"""

from sqlalchemy import text

BUCKETS = 20


def score_histogram(db) -> list[dict]:
    rows = db.execute(text("""
        SELECT width_bucket(score, 0, 1, :n) AS bucket, COUNT(*) AS n
        FROM articles WHERE score IS NOT NULL
        GROUP BY bucket ORDER BY bucket
    """), {"n": BUCKETS}).mappings().all()
    counts = {r["bucket"]: r["n"] for r in rows}
    out = []
    for b in range(1, BUCKETS + 1):
        lo = (b - 1) / BUCKETS
        out.append({"lo": lo, "hi": lo + 1 / BUCKETS,
                    "n": counts.get(b, 0) + (counts.get(BUCKETS + 1, 0) if b == BUCKETS else 0)})
    return out


def agreement(db, threshold: float) -> dict:
    """How often the score agreed with the vote.

    A like that scored below the threshold would have been hidden from you; a
    dislike above it took up space. Both are the ranking being wrong.
    """
    row = db.execute(text("""
        SELECT
          COUNT(*) FILTER (WHERE v.value = 1)                            AS likes,
          COUNT(*) FILTER (WHERE v.value = -1)                           AS dislikes,
          COUNT(*) FILTER (WHERE v.value = 1  AND a.score >= :t)         AS likes_ok,
          COUNT(*) FILTER (WHERE v.value = -1 AND a.score <  :t)         AS dislikes_ok
        FROM votes v JOIN articles a ON a.id = v.article_id
        WHERE a.score IS NOT NULL
    """), {"t": threshold}).mappings().first()
    likes, dislikes = row["likes"] or 0, row["dislikes"] or 0
    ok = (row["likes_ok"] or 0) + (row["dislikes_ok"] or 0)
    total = likes + dislikes
    return {
        "votes": total,
        "agreed": ok,
        "rate": round(100 * ok / total) if total else None,
        "likes": likes, "dislikes": dislikes,
        "likes_ok": row["likes_ok"] or 0, "dislikes_ok": row["dislikes_ok"] or 0,
    }


def suggest_threshold(db) -> dict | None:
    """Sweep 0→1 and pick the threshold that best matches your votes."""
    rows = db.execute(text("""
        SELECT v.value, a.score FROM votes v JOIN articles a ON a.id = v.article_id
        WHERE a.score IS NOT NULL
    """)).all()
    if not rows:
        return None
    best, best_rate = None, -1.0
    for step in range(0, 101, 5):
        t = step / 100
        ok = sum(1 for value, score in rows
                 if (value == 1 and score >= t) or (value == -1 and score < t))
        rate = ok / len(rows)
        if rate > best_rate:
            best, best_rate = t, rate
    return {"threshold": best, "rate": round(100 * best_rate), "votes": len(rows)}


def per_feed(db) -> list[dict]:
    """Like-rate by feed. A feed you never like is a feed to drop."""
    return db.execute(text("""
        SELECT COALESCE(f.title, f.url) AS feed,
               COUNT(*) FILTER (WHERE v.value = 1)  AS likes,
               COUNT(*) FILTER (WHERE v.value = -1) AS dislikes,
               COUNT(a.id)                          AS articles
        FROM feeds f
        LEFT JOIN articles a ON a.feed_id = f.id
        LEFT JOIN votes v    ON v.article_id = a.id
        GROUP BY f.id, f.title, f.url ORDER BY COALESCE(f.title, f.url)
    """)).mappings().all()


def per_topic(db, limit: int = 15) -> list[dict]:
    return db.execute(text("""
        SELECT t.topic,
               COUNT(*) FILTER (WHERE v.value = 1)  AS likes,
               COUNT(*) FILTER (WHERE v.value = -1) AS dislikes
        FROM articles a
        CROSS JOIN LATERAL unnest(a.topics) AS t(topic)
        JOIN votes v ON v.article_id = a.id
        GROUP BY t.topic
        HAVING COUNT(*) > 0
        ORDER BY COUNT(*) DESC LIMIT :n
    """), {"n": limit}).mappings().all()


def recent_runs(db, limit: int = 20) -> list[dict]:
    """Turns LOG_FORMAT=json timings into something visible."""
    return db.execute(text("""
        SELECT started_at, finished_at, scored_n, summarized_n, errors_n, skipped,
               EXTRACT(EPOCH FROM (finished_at - started_at)) AS seconds
        FROM pipeline_runs ORDER BY started_at DESC LIMIT :n
    """), {"n": limit}).mappings().all()


def pipeline_health(db) -> dict:
    row = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE status = 'new')        AS unscored,
               COUNT(*) FILTER (WHERE status = 'scored')     AS unsummarized,
               COUNT(*) FILTER (WHERE status = 'hidden')     AS hidden,
               COUNT(*) FILTER (WHERE status = 'summarized') AS ready,
               COUNT(*)                                      AS total
        FROM articles
    """)).mappings().first()
    return dict(row) if row else {}

"""What the reader's own votes say about a topic, as a number.

Measured on the owner's 2,149 votes, held out 5-fold:

    LLM relevance score                 AUC 0.524   (0.50 is a coin flip)
    topic affinity from their votes     AUC 0.756
    50/50 blend of the two              AUC 0.632
    affinity, falling back to the LLM   AUC 0.726

The blend scoring *worse* than affinity alone is the finding that matters: the
model's holistic judgement was not a weak signal to be improved, it was noise
that dragged a good signal down. Its best possible threshold agreed with the
reader 59.5% of the time, against 61.4% for a rule that simply hid everything.

So the score a reader sees is now their own record where they have one, and the
model's opinion only where they do not. The model still earns its keep: it reads
the article and assigns the topics this is computed from, which it does well --
93.6% of articles carry them.
"""

from sqlalchemy import text

# Below this many votes a topic is an anecdote, not evidence. Swept over the
# real data: 1 -> 0.739, 3 -> 0.726, 5 -> 0.715, 20 -> 0.702. Low bars score
# marginally better but let a single vote move an article a long way, which is
# indefensible to a reader who can see the vote.
MIN_VOTES = 3

# Pulls a topic's rate toward the reader's own like-rate, in units of votes: a
# topic with 8 votes sits halfway between its own rate and the baseline. Without
# it, one like on a new topic reads as 100% affinity.
SMOOTHING = 8.0

# Below this, affinity is not applied at all. Two separate failure modes, both
# seen on a real database: with 16 topic-carrying votes that were *all* likes,
# the baseline is 1.0, every topic smooths to 1.0, and every article scores
# identically -- which does not merely fail to help, it destroys the ranking
# inside the kept set. A reader needs enough votes, and enough of *both* kinds,
# before their record is worth more than the model's guess.
MIN_TOTAL_VOTES = 40
MIN_PER_CLASS = 8


def topic_affinity(db, user_id: int) -> dict[str, float]:
    """Like-rate per topic for one reader, smoothed, for topics with evidence.

    Reads `topics_snapshot` off the vote rather than joining `articles`, because
    retention deletes articles and the vote outlives them -- the same reason
    votes already carry title and summary snapshots.
    """
    rows = db.execute(text("""
        SELECT unnest(topics_snapshot) AS topic,
               COUNT(*)                        AS n,
               COUNT(*) FILTER (WHERE value = 1) AS likes
        FROM votes
        WHERE user_id = :u AND topics_snapshot IS NOT NULL
        GROUP BY 1
    """), {"u": user_id}).mappings().all()
    if not rows:
        return {}

    total = sum(r["n"] for r in rows)
    liked = sum(r["likes"] for r in rows)
    disliked = total - liked
    if (total < MIN_TOTAL_VOTES
            or liked < MIN_PER_CLASS or disliked < MIN_PER_CLASS):
        # Not enough to beat the model yet. Returning {} makes `adjust` a no-op
        # rather than a constant, which is the important difference.
        return {}
    baseline = liked / total

    return {
        r["topic"]: (r["likes"] + SMOOTHING * baseline) / (r["n"] + SMOOTHING)
        for r in rows if r["n"] >= MIN_VOTES
    }


def owner_id(db) -> int | None:
    """Whose votes drive the shared score.

    The lowest user id, matching how `pipeline` already picks whose profile to
    score against. A second reader's taste does not move the shared score;
    changing that means scoring every article once per reader, which is a real
    cost decision rather than something to slip in here.
    """
    row = db.execute(text("SELECT MIN(user_id) FROM votes")).first()
    return row[0] if row and row[0] is not None else None


def adjust(llm_score: float, topics: list[str], affinity: dict[str, float]) -> tuple[float, str | None]:
    """The reader's own record where it exists, the model's guess where it does not.

    Not an average of the two. Blending measured *worse* than affinity alone
    (0.632 against 0.756), because averaging a real signal with a noisy one
    mostly adds noise.
    """
    if not affinity or not topics:
        return llm_score, None
    known = [affinity[t] for t in topics if t in affinity]
    if not known:
        return llm_score, None
    score = sum(known) / len(known)
    matched = [t for t in topics if t in affinity]
    return score, f"Your votes on {', '.join(sorted(matched)[:3])}"


def evidence_block(db, user_id: int, limit: int = 14) -> str:
    """The same numbers as prose, for the prompts.

    The profile the model wrote for this reader claimed they valued "crime and
    legal stories" and "health and psychology"; their votes put those at 23% and
    16% like-rates, two of the things they reject most. It named none of their
    top four. Handing the model the counts instead of asking it to infer them
    from a list of headlines is the difference.
    """
    rows = db.execute(text("""
        SELECT unnest(topics_snapshot) AS topic,
               COUNT(*)                          AS n,
               COUNT(*) FILTER (WHERE value = 1) AS likes
        FROM votes
        WHERE user_id = :u AND topics_snapshot IS NOT NULL
        GROUP BY 1 HAVING COUNT(*) >= :m
        ORDER BY COUNT(*) DESC
    """), {"u": user_id, "m": MIN_VOTES}).mappings().all()
    if not rows:
        return ""

    scored = sorted(((r["likes"] / r["n"], r["topic"], r["n"]) for r in rows),
                    reverse=True)
    likes = [f"{t} ({rate:.0%} of {n})" for rate, t, n in scored[:limit] if rate >= 0.5]
    avoids = [f"{t} ({rate:.0%} of {n})" for rate, t, n in reversed(scored[-limit:])
              if rate < 0.35]
    if not likes and not avoids:
        return ""
    out = "\nWHAT THIS READER ACTUALLY VOTED ON (counts, not impressions):\n"
    if likes:
        out += f"- Keeps: {', '.join(likes)}\n"
    if avoids:
        out += f"- Rejects: {', '.join(avoids)}\n"
    out += ("These percentages are the reader's own record and outrank anything "
            "inferred from a headline.\n")
    return out

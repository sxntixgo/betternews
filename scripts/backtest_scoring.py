"""Re-score the articles you have voted on, and report whether the scorer agrees.

Every vote is a labelled example: a like means "this should have scored high", a
dislike means "this should have scored low". Nothing was ever checked against
them, which is how the scorer came to give 0.00 to a tournament named in the
reader's own profile.

Run it where Ollama is reachable:

    docker compose run --rm web python scripts/backtest_scoring.py
    docker compose run --rm web python scripts/backtest_scoring.py --apply

Without `--apply` it writes nothing -- it scores into memory and prints the
comparison, so you can see whether a prompt change helped before it touches the
reading list. With `--apply` it writes the new scores and un-hides anything that
now clears the threshold.
"""

import argparse
import os
import sys

# Run as a script, not a module, so the package root has to go on the path --
# same as scripts/import_sqlite.py and scripts/backup.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app import create_app, prompts
from app.db import get_db_direct, get_setting
from app.pipeline import SCORE_THRESHOLD, SCORING_SNIPPET_CHARS, ollama_base
from app import ollama_client, llm_config, topics as topics_mod


def voted_articles(db):
    """Every article this reader voted on, with the vote as the label."""
    return db.execute(text("""
        SELECT v.user_id, v.value, a.id, a.title, a.raw_snippet, a.score
        FROM votes v JOIN articles a ON a.id = v.article_id
        WHERE a.id IS NOT NULL
        ORDER BY v.user_id, v.created_at
    """)).mappings().all()


def profile_for(db, user_id: int) -> str:
    row = db.execute(text("SELECT profile_text FROM preferences WHERE user_id = :u"),
                     {"u": user_id}).first()
    return (row[0] if row else "") or ""


def rescore(db, rows, model, base):
    """One call per article. Slower than the batch path and deliberately so:
    this is measuring the prompt, not the batching."""
    out = {}
    vocab = topics_mod.vocabulary(db)
    for i, r in enumerate(rows, 1):
        prompt = prompts.scoring_prompt(
            profile_for(db, r["user_id"]), r["title"],
            (r["raw_snippet"] or "")[:SCORING_SNIPPET_CHARS], vocabulary=vocab)
        reply = ollama_client.generate(model=model, prompt=prompt, expect_json=True,
                                       base_url=base, action="scoring (backtest)")
        if not isinstance(reply, dict):
            print(f"  [{i}/{len(rows)}] no usable reply for {r['id']}", file=sys.stderr)
            continue
        try:
            score = max(0.0, min(1.0, float(reply.get("score", 0.5))))
        except (TypeError, ValueError):
            continue
        out[r["id"]] = {"score": score, "reason": str(reply.get("reason", "")),
                        "topics": topics_mod.normalize(reply.get("topics"))}
        print(f"  [{i}/{len(rows)}] {r['id']} {r['score']} -> {score:.2f}  {r['title'][:54]}",
              file=sys.stderr)
    return out


def agreement(rows, score_of, threshold):
    """How often the score lands on the same side of the threshold as the vote."""
    likes = [r for r in rows if r["value"] == 1]
    dislikes = [r for r in rows if r["value"] == -1]
    likes_ok = sum(1 for r in likes if (score_of(r) or 0) >= threshold)
    dislikes_ok = sum(1 for r in dislikes if (score_of(r) or 0) < threshold)
    total = len(likes) + len(dislikes)
    return {
        "likes": len(likes), "likes_ok": likes_ok,
        "dislikes": len(dislikes), "dislikes_ok": dislikes_ok,
        "rate": round(100 * (likes_ok + dislikes_ok) / total) if total else None,
        # The failure that prompted this: liked articles scored below the bar.
        "liked_but_hidden": [r for r in likes if (score_of(r) or 0) < threshold],
    }


def report(label, stats):
    print(f"\n{label}")
    print(f"  agreement      {stats['rate']}%")
    print(f"  likes above    {stats['likes_ok']}/{stats['likes']}")
    print(f"  dislikes below {stats['dislikes_ok']}/{stats['dislikes']}")
    if stats["liked_but_hidden"]:
        print(f"  liked but hidden ({len(stats['liked_but_hidden'])}):")
        for r in stats["liked_but_hidden"][:10]:
            print(f"    - {r['title'][:70]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the new scores; without it nothing is written")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        db = get_db_direct()
        try:
            rows = voted_articles(db)
            if not rows:
                print("No votes yet, so there is nothing to measure against.")
                return 1
            threshold = float(get_setting(db, "score_threshold", "") or SCORE_THRESHOLD)
            base = ollama_base(db)
            model = llm_config.model_for(db, "scoring")
            print(f"{len(rows)} voted articles · model {model} · threshold {threshold}")

            before = agreement(rows, lambda r: r["score"], threshold)
            report("BEFORE (scores currently stored)", before)

            fresh = rescore(db, rows, model, base)
            if not fresh:
                print("\nNothing was re-scored -- is Ollama reachable?")
                return 1
            after = agreement(rows, lambda r: fresh.get(r["id"], {}).get("score"), threshold)
            report("AFTER (re-scored with the current prompt)", after)

            delta = (after["rate"] or 0) - (before["rate"] or 0)
            print(f"\nagreement {before['rate']}% -> {after['rate']}%  ({delta:+d} points)")

            if not args.apply:
                print("\nNothing written. Re-run with --apply to keep these scores.")
                return 0

            for aid, r in fresh.items():
                db.execute(text("""
                    UPDATE articles
                       SET score = :s, score_reason = :r, topics = :t,
                           status = CASE WHEN :s >= :th AND status = 'hidden'
                                         THEN 'scored' ELSE status END
                     WHERE id = :i
                """), {"s": r["score"], "r": r["reason"], "t": r["topics"],
                       "th": threshold, "i": aid})
            db.commit()
            print(f"\nWrote {len(fresh)} scores. Anything that now clears the "
                  f"threshold is queued for summarizing.")
            return 0
        finally:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())

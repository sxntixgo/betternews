"""`GET /digest/meta` -- what the "what you missed" strip shows.

Must not generate the briefing (`GET /digest` does that, an LLM call). This
only touches `users.last_seen_at` and counts rows, so a page load never costs
a model call.
"""

from datetime import datetime, timedelta, timezone

from tests.conftest import add_article, add_feed

API = "/api/v1"


def test_first_visit_reports_no_since_label_and_full_unread_count(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        for i in range(3):
            add_article(db, fid, seq=i, guid=f"m{i}")
        db.close()

    got = client.get(f"{API}/digest/meta").get_json()
    assert got["since_label"] is None
    assert got["story_count"] == 3
    assert got["read_minutes"] >= 1


def test_second_visit_within_the_window_keeps_the_same_since_label(client, app, admin_user):
    from app.db import get_db_direct
    from app.repo.users import touch_last_seen

    # Seeded well inside the 30-minute staleness window relative to the real
    # clock the endpoint uses, so the endpoint's own calls do not themselves
    # trigger an advance.
    t0 = datetime.now(timezone.utc) - timedelta(minutes=5)
    with app.app_context():
        db = get_db_direct()
        touch_last_seen(db, admin_user, now=t0)
        db.commit()
        db.close()

    first = client.get(f"{API}/digest/meta").get_json()
    second = client.get(f"{API}/digest/meta").get_json()

    assert first["since_label"] == t0.strftime("%A")
    assert second["since_label"] == first["since_label"], (
        "a second visit inside the staleness window must not advance the "
        "stored last_seen_at, or the label resets every time you look at it"
    )


def test_a_visit_after_the_window_advances_the_stored_value(client, app, admin_user):
    from app.db import get_db_direct
    from app.repo.users import touch_last_seen

    with app.app_context():
        db = get_db_direct()
        t0 = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)  # a Thursday
        touch_last_seen(db, admin_user, now=t0)
        db.commit()
        db.close()

    with app.app_context():
        db = get_db_direct()
        t1 = t0 + timedelta(minutes=31)
        prev = touch_last_seen(db, admin_user, now=t1)
        db.commit()
        db.close()
    assert prev == t0

    with app.app_context():
        db = get_db_direct()
        t2 = t1 + timedelta(minutes=1)
        prev2 = touch_last_seen(db, admin_user, now=t2)
        db.close()
    assert prev2 == t1, "the stored value should have advanced to t1 after the stale visit"


def test_story_count_counts_only_articles_created_since_the_previous_visit(client, app, admin_user):
    from app.db import get_db_direct
    from app.repo.users import touch_last_seen

    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db)
        old_cutoff = datetime.now(timezone.utc) - timedelta(days=2)
        # 2 articles created before the previous visit, 4 after it.
        for i in range(2):
            add_article(db, fid, seq=i, guid=f"old{i}",
                        created_at=old_cutoff - timedelta(hours=1))
        touch_last_seen(db, admin_user, now=old_cutoff)
        db.commit()
        for i in range(4):
            add_article(db, fid, seq=i, guid=f"new{i}",
                        created_at=old_cutoff + timedelta(hours=1))
        db.commit()
        db.close()

    got = client.get(f"{API}/digest/meta").get_json()
    assert got["story_count"] == 4


def test_the_endpoint_requires_a_token_or_session(app):
    anon = app.test_client()
    r = anon.get(f"{API}/digest/meta")
    assert r.status_code == 401
    assert r.is_json

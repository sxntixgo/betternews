"""Markdown export — a reading tool should let its data leave."""

import io
import zipfile

import pytest
from sqlalchemy import text

from app import export
from tests.conftest import add_article, add_feed, add_user


def _uid(db):
    from app.repo.users import ensure_bootstrap_user
    uid = ensure_bootstrap_user(db)
    db.commit()
    return uid


def _names(data):
    return sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())


def _read(data, name):
    return zipfile.ZipFile(io.BytesIO(data)).read(name).decode()


# ── front matter ───────────────────────────────────────────────────────────────

def test_front_matter_has_the_expected_fields(db_conn):
    uid = _uid(db_conn)
    add_article(db_conn, add_feed(db_conn, title="A Feed"),
                title="A Story", summary="What happened.", full_text="Body.")
    data, n = export.build_zip(db_conn, uid, "all")
    md = _read(data, _names(data)[0])
    assert md.startswith("---")
    for field in ("title:", "url:", "feed:", "published:", "score:", "topics:", "exported:"):
        assert field in md
    assert "# A Story" in md and "Body." in md


def test_quotes_and_colons_in_titles_do_not_break_yaml(db_conn):
    """A colon in a headline is common and would otherwise corrupt the file."""
    uid = _uid(db_conn)
    add_article(db_conn, add_feed(db_conn),
                title='Report: the "big" one', summary="s", full_text="b")
    data, _ = export.build_zip(db_conn, uid, "all")
    md = _read(data, _names(data)[0])
    assert 'title: "Report: the \\"big\\" one"' in md


def test_the_original_title_is_kept_alongside_a_rewrite(db_conn):
    uid = _uid(db_conn)
    aid = add_article(db_conn, add_feed(db_conn), title="You won't believe")
    db_conn.execute(text("UPDATE articles SET clean_title='Council approves budget', "
                         "title_was_clickbait=true WHERE id=:i"), {"i": aid})
    db_conn.commit()
    md = _read(*( (lambda d: (d, _names(d)[0]))(export.build_zip(db_conn, uid, "all")[0]) ))
    assert "Council approves budget" in md
    assert "original_title:" in md and "You won't believe" in md


def test_missing_full_text_is_stated_not_blank(db_conn):
    uid = _uid(db_conn)
    add_article(db_conn, add_feed(db_conn), full_text=None)
    data, _ = export.build_zip(db_conn, uid, "all")
    assert "_No full text was extracted" in _read(data, _names(data)[0])


# ── scopes ─────────────────────────────────────────────────────────────────────

def test_saved_scope_only_includes_saves(db_conn):
    from app.repo.articles import toggle_saved
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    keep = add_article(db_conn, fid, seq=1, guid="a", title="Kept")
    add_article(db_conn, fid, seq=2, guid="b", title="Ignored")
    toggle_saved(db_conn, uid, keep)
    db_conn.commit()
    data, n = export.build_zip(db_conn, uid, "saved")
    assert n == 1 and "kept" in _names(data)[0]


def test_liked_scope_only_includes_likes(db_conn):
    from app.repo.articles import record_vote
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    liked = add_article(db_conn, fid, seq=1, guid="a", title="Liked")
    disliked = add_article(db_conn, fid, seq=2, guid="b", title="Disliked")
    record_vote(db_conn, uid, liked, 1)
    record_vote(db_conn, uid, disliked, -1)
    db_conn.commit()
    data, n = export.build_zip(db_conn, uid, "liked")
    assert n == 1 and "liked" in _names(data)[0]


def test_dismissed_articles_are_never_exported(db_conn):
    from app.repo.articles import dismiss
    uid = _uid(db_conn)
    aid = add_article(db_conn, add_feed(db_conn))
    dismiss(db_conn, uid, aid)
    db_conn.commit()
    _, n = export.build_zip(db_conn, uid, "all")
    assert n == 0


def test_export_is_scoped_to_the_calling_user(db_conn):
    from app.repo.articles import toggle_saved
    a = _uid(db_conn)
    b = add_user(db_conn, username="second", role="user")
    aid = add_article(db_conn, add_feed(db_conn))
    toggle_saved(db_conn, a, aid)
    db_conn.commit()
    assert export.build_zip(db_conn, a, "saved")[1] == 1
    assert export.build_zip(db_conn, b, "saved")[1] == 0


def test_empty_export_still_produces_a_readable_zip(db_conn):
    uid = _uid(db_conn)
    data, n = export.build_zip(db_conn, uid, "saved")
    assert n == 0 and _names(data) == ["README.md"]


# ── filenames ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,fragment", [
    ("Hello World", "hello-world"),
    # Accents are kept — half these feeds are Spanish, and stripping them would
    # turn "Rosario: mataron a un agente" into mush.
    ("Ünïcödé & symbols!", "ünïcödé-symbols"),
    ("Alerta en Los Ángeles, hoy", "alerta-en-los-ángeles-hoy"),
    ("", "article-"),
])
def test_filenames_are_slugged(db_conn, title, fragment):
    uid = _uid(db_conn)
    add_article(db_conn, add_feed(db_conn), title=title or "x")
    data, _ = export.build_zip(db_conn, uid, "all")
    name = _names(data)[0]
    assert name.endswith(".md")
    if title:
        assert fragment in name


def test_articles_sharing_a_headline_get_distinct_files(db_conn):
    uid = _uid(db_conn)
    fid = add_feed(db_conn)
    add_article(db_conn, fid, seq=1, guid="a", title="Same Headline")
    add_article(db_conn, fid, seq=2, guid="b", title="Same Headline")
    data, n = export.build_zip(db_conn, uid, "all")
    assert n == 2 and len(_names(data)) == 2


# ── route ──────────────────────────────────────────────────────────────────────

def test_route_returns_a_zip(client, app):
    from app.db import get_db_direct
    with app.app_context():
        db = get_db_direct()
        add_article(db, add_feed(db))
        db.close()
    r = client.get("/export/markdown?scope=all")
    assert r.status_code == 200
    assert r.mimetype == "application/zip"
    assert "attachment" in r.headers["Content-Disposition"]
    assert zipfile.ZipFile(io.BytesIO(r.data)).namelist()


def test_route_rejects_an_unknown_scope(client):
    assert client.get("/export/markdown?scope=everything-ever").status_code == 400


def test_route_requires_a_session(anon_client):
    assert anon_client.get("/export/markdown").status_code == 302


def test_plain_users_can_export_their_own(login_as):
    c, _ = login_as()
    assert c.get("/export/markdown?scope=saved").status_code == 200

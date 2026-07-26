import logging
import re
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from html import escape

from flask import (Blueprint, current_app, g, redirect, render_template,
                   request, Response, url_for)

from sqlalchemy import text as sql

from app import content_filter, ollama_client
from app import (auth, digest as digest_mod, export as export_mod, extract,
                 health, insights, retention, topics as topics_mod)
from app.repo import articles as art_repo, users as user_repo
from app.db import get_db, get_setting, set_setting
from app.pipeline import DEFAULT_SCORING_MODEL, DEFAULT_SUMMARY_MODEL, ollama_base

log = logging.getLogger(__name__)

bp = Blueprint("main", __name__)

_READ_TIME_RE = re.compile(
    r'-?\s*(\d+)\s*min(?:uto)?s?\s*(?:de\s+)?(?:read(?:ing)?|lectura)'
    r'|lectura\s*[:\-]?\s*\d+\s*min'
    r'|tiempo\s+de\s+lectura\b',
    re.IGNORECASE,
)

_BULLET_RE = re.compile(r'^[-*•‣◦∙·–—]\s+(.+)$')

# Detect a line that is *only* a tweet permalink — `(?:www\.|mobile\.)?` covers
# both bare `twitter.com` and the `www.` / `mobile.` variants; `x.com` is the
# rebranded host. Matches plain text URLs left over after trafilatura strips
# `<blockquote class="twitter-tweet">` wrappers down to text.
_TWITTER_URL_RE = re.compile(
    r'^https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/'
    r'[A-Za-z0-9_]+/status/\d+(?:\?[^\s]*)?/?$',
    re.IGNORECASE,
)
_INSTAGRAM_URL_RE = re.compile(
    r'^https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/'
    r'[A-Za-z0-9_-]+/?(?:\?[^\s]*)?$',
    re.IGNORECASE,
)


def _embed_match(line: str) -> tuple[str, str] | None:
    if _TWITTER_URL_RE.match(line):
        return ("twitter", line)
    if _INSTAGRAM_URL_RE.match(line):
        return ("instagram", line)
    return None


def _extract_reading_time(text: str) -> str | None:
    m = _READ_TIME_RE.search(text or "")
    if not m:
        return None
    num = re.search(r'\d+', m.group(0))
    return num.group(0) if num else None


def _clean_content(text: str, title: str = "", description: str = "") -> str:
    """Drop reading-time furniture and a leading line duplicating the title.

    Related-story rails and pagination markers used to be *deleted* here. They
    are now classified as asides by `content_filter` instead, so the reader can
    frame them or hide them recoverably rather than silently truncating the
    body. See `_content_blocks`.
    """
    cleaned = []
    title_norm = (title or "").strip().lower()
    desc_norm = (description or "").strip().lower()[:120]
    for line in text.split('\n'):
        s = line.strip()
        if not s:
            continue
        if _READ_TIME_RE.search(s):
            continue
        s_norm = s.lower()
        # Skip a leading line that duplicates the title or description
        if not cleaned and title_norm and (s_norm == title_norm or s_norm.startswith(title_norm)):
            continue
        if not cleaned and desc_norm and s_norm.startswith(desc_norm[:60]):
            continue
        cleaned.append(s)
    return '\n'.join(cleaned)


def _to_blocks(text: str, embeds_enabled: bool = False,
               aside_kinds: list[str | None] | None = None) -> list[dict]:
    """Group consecutive bullet-prefixed lines into list blocks for rendering.

    Lines starting with ``-``, ``*``, ``•`` (and similar marks) followed by a
    space are turned into ``<li>`` items grouped under a single ``<ul>``.

    When ``embeds_enabled`` is true, a line that is *only* a Twitter/X or
    Instagram permalink becomes an ``embed`` block; the modal turns those into
    proper blockquotes the official scripts can hydrate. When disabled the URL
    falls through as a normal paragraph.

    ``aside_kinds`` carries one entry per non-empty line, tagging blocks that
    `content_filter` judged to be padding.
    """
    blocks: list[dict] = []
    current: list[str] | None = None
    idx = -1
    for line in text.split('\n'):
        s = line.strip()
        if not s:
            continue
        idx += 1
        kind = aside_kinds[idx] if aside_kinds and idx < len(aside_kinds) else None
        if embeds_enabled:
            em = _embed_match(s)
            if em:
                current = None
                b = {"type": "embed", "platform": em[0], "url": em[1]}
                if kind:
                    b["aside"] = kind
                blocks.append(b)
                continue
        m = _BULLET_RE.match(s)
        # A bullet run is only continued while its aside classification matches,
        # so a rail starting mid-list doesn't drag the real items into the aside.
        if m and current is not None and blocks[-1].get("aside") == kind:
            current.append(m.group(1).strip())
        elif m:
            current = [m.group(1).strip()]
            b = {"type": "ul", "items": current}
            if kind:
                b["aside"] = kind
            blocks.append(b)
        else:
            current = None
            b = {"type": "p", "text": s}
            if kind:
                b["aside"] = kind
            blocks.append(b)
    return blocks


def _group_blocks(blocks: list[dict]) -> list[dict]:
    """Collapse consecutive aside blocks into one group.

    A related-stories rail becomes a single foldable item rather than one per
    paragraph. Body blocks pass through in a group of their own.
    """
    groups: list[dict] = []
    for b in blocks:
        kind = b.get("aside")
        if groups and groups[-1]["aside"] == kind:
            groups[-1]["blocks"].append(b)
        else:
            groups.append({
                "aside": kind,
                "label": content_filter.LABELS.get(kind, "Aside") if kind else None,
                "blocks": [b],
            })
    return groups


def _content_blocks(text: str, embeds_enabled: bool, mode: str,
                    stored_asides: str | None = None) -> tuple[list[dict], int]:
    """Grouped blocks for the reader, plus how many were classified as padding.

    In ``off`` mode nothing is classified, so the body renders whole.
    """
    if mode == content_filter.MODE_OFF:
        blocks = _to_blocks(text, embeds_enabled=embeds_enabled)
        return _group_blocks(blocks), 0
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    kinds = content_filter.classify_lines(
        lines, content_filter.load_stored(stored_asides)
    )
    blocks = _to_blocks(text, embeds_enabled=embeds_enabled, aside_kinds=kinds)
    n = sum(1 for b in blocks if b.get("aside"))
    return _group_blocks(blocks), n


def _content_filter_mode(db) -> str:
    mode = get_setting(db, "content_filter_mode", content_filter.MODE_REMOVE)
    return mode if mode in content_filter.MODES else content_filter.MODE_REMOVE


def _row_to_article(row, declickbait: bool = False) -> dict:
    d = dict(row)
    text = (d.get('full_text_head') or '') + ' ' + (d.get('raw_snippet') or '')
    d['reading_time'] = _extract_reading_time(text)
    d['display_title'], d['original_title'] = _resolve_title(d, declickbait)
    return d


def current_user_id(db) -> int:
    """The acting user, from the session.

    Every route reaching this is behind `login_required`, so a missing session
    is a programming error rather than an anonymous visitor.
    """
    uid = auth.current_user_id()
    if uid is None:                                   # pragma: no cover - guarded
        raise RuntimeError("no authenticated user in request context")
    return uid


def _declickbait(db) -> bool:
    return get_setting(db, "declickbait_enabled", "") == "1"


def _resolve_title(d: dict, declickbait: bool) -> tuple[str, str | None]:
    """(title to show, original to show beneath — None when unchanged).

    Falls back to the stored title whenever the rewrite is absent or the setting
    is off, so articles summarized before the feature existed render unchanged.
    """
    title = d.get('title') or ''
    if not declickbait:
        return title, None
    clean = (d.get('clean_title') or '').strip()
    if not clean or not d.get('title_was_clickbait') or clean == title:
        return title, None
    return clean, title


# ── Accounts ───────────────────────────────────────────────────────────────────

@bp.get("/login")
def login():
    if auth.current_user():
        return redirect(url_for("main.index"))
    db = get_db()
    return render_template("login.html", first_run=user_repo.count(db) == 0)


@bp.post("/login")
def login_post():
    db = get_db()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if auth.is_locked_out(db, username):
        return render_template(
            "login.html", error="Too many failed attempts. Try again shortly.",
            username=username, first_run=False), 429

    user = user_repo.by_username(db, username)
    if not user or not auth.verify_password(user["password_hash"], password):
        auth.record_failure(db, username)
        db.commit()
        return render_template(
            "login.html", error="Wrong username or password.",
            username=username, first_run=user_repo.count(db) == 0), 401

    auth.clear_failures(db, username)
    auth.login_user(db, user["id"])
    db.commit()
    return redirect(url_for("main.index"))


@bp.get("/register")
def register():
    if auth.current_user():
        return redirect(url_for("main.index"))
    db = get_db()
    return render_template("register.html", first_run=user_repo.count(db) == 0)


@bp.post("/register")
def register_post():
    db = get_db()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    first_run = user_repo.count(db) == 0

    def fail(msg, code=400):
        return render_template("register.html", error=msg, username=username,
                               first_run=first_run), code

    if not username:
        return fail("Username is required.")
    if len(username) > 60:
        return fail("Username is too long.")
    problem = auth.password_problem(password, confirm)
    if problem:
        return fail(problem)
    if user_repo.by_username(db, username):
        return fail("That username is taken.", 409)

    uid = auth.register_user(db, username, password)
    auth.login_user(db, uid)
    db.commit()
    log.info("Registered user %r (id=%d)", username, uid)
    return redirect(url_for("main.index"))


@bp.post("/logout")
@bp.get("/logout")
def logout():
    auth.logout_user()
    return redirect(url_for("main.login"))


@bp.get("/profile")
@auth.login_required
def profile():
    db = get_db()
    user = auth.current_user()
    return render_template("profile.html", user=user,
                           stats=user_repo.stats(db, user["id"]))


@bp.post("/profile/password")
@auth.login_required
def profile_password():
    db = get_db()
    user = auth.current_user()
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    def render(error=None, saved=False):
        return render_template("_profile_password.html", error=error, saved=saved,
                               must_change=user["must_change_password"])

    # A forced change has no working current password to prove.
    if not user["must_change_password"] and not auth.verify_password(
            user["password_hash"], current):
        return render(error="Current password is wrong.")
    problem = auth.password_problem(new, confirm)
    if problem:
        return render(error=problem)

    db.execute(sql(
        "UPDATE users SET password_hash=:h, must_change_password=false WHERE id=:id"),
        {"h": auth.hash_password(new), "id": user["id"]})
    db.commit()
    g.pop("current_user", None)
    return render(saved=True)


# ── Admin: user management ─────────────────────────────────────────────────────

@bp.get("/admin/users")
@auth.admin_required
def admin_users():
    db = get_db()
    return render_template("admin_users.html", users=user_repo.all_with_stats(db),
                           me=auth.current_user_id())


def _users_fragment(db, **kw):
    return render_template("_admin_user_rows.html", users=user_repo.all_with_stats(db),
                           me=auth.current_user_id(), **kw)


@bp.post("/admin/users/<int:user_id>/reset-password")
@auth.admin_required
def admin_reset_password(user_id: int):
    """Set a temporary password, shown once, and force a change at next login."""
    db = get_db()
    target = user_repo.get(db, user_id)
    if not target:
        return Response("no such user", status=404)
    temp = request.form.get("temp_password", "").strip() or user_repo.generate_password()
    problem = auth.password_problem(temp)
    if problem:
        return _users_fragment(db, error=problem)
    db.execute(sql(
        "UPDATE users SET password_hash=:h, must_change_password=true WHERE id=:id"),
        {"h": auth.hash_password(temp), "id": user_id})
    db.commit()
    log.info("Admin reset password for user id=%d", user_id)
    return _users_fragment(db, temp_password=temp, temp_for=target["username"])


@bp.post("/admin/users/<int:user_id>/role")
@auth.admin_required
def admin_set_role(user_id: int):
    db = get_db()
    role = request.form.get("role", "")
    if role not in ("user", "admin"):
        return Response("invalid role", status=400)
    target = user_repo.get(db, user_id)
    if not target:
        return Response("no such user", status=404)
    # Locking the row keeps two simultaneous demotions from leaving zero admins.
    db.execute(sql("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
    if role == "user" and target["role"] == "admin" and auth.count_admins(db) <= 1:
        return _users_fragment(db, error="That is the last admin — promote someone else first.")
    db.execute(sql("UPDATE users SET role=:r WHERE id=:id"), {"r": role, "id": user_id})
    db.commit()
    return _users_fragment(db)


@bp.post("/admin/users/<int:user_id>/delete")
@auth.admin_required
def admin_delete_user(user_id: int):
    db = get_db()
    target = user_repo.get(db, user_id)
    if not target:
        return Response("no such user", status=404)
    db.execute(sql("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
    if target["role"] == "admin" and auth.count_admins(db) <= 1:
        return _users_fragment(db, error="That is the last admin — promote someone else first.")
    if user_id == auth.current_user_id():
        return _users_fragment(db, error="You cannot delete your own account.")
    db.execute(sql("DELETE FROM users WHERE id=:id"), {"id": user_id})
    db.commit()
    log.info("Admin deleted user id=%d (%s)", user_id, target["username"])
    return _users_fragment(db)


# ── Pages ──────────────────────────────────────────────────────────────────────

@bp.get("/")
@auth.login_required
def index():
    return render_template("index.html")


@bp.get("/settings")
@auth.admin_required
def settings():
    return render_template("settings.html")


@bp.get("/manage-feeds")
@auth.admin_required
def manage_feeds():
    return render_template("manage_feeds.html")


# ── Article fragments ──────────────────────────────────────────────────────────

_PAGE_SIZE = 50


@bp.get("/articles")
@auth.login_required
def articles():
    sort = request.args.get("sort", "date")
    order = "published_at DESC" if sort == "date" else "score DESC, published_at DESC"
    # ?hidden=1 means show ONLY hidden articles (the sidebar "Hidden" group),
    # not "include hidden in the normal list". ?saved=1 means show ONLY saved.
    show_hidden = request.args.get("hidden") == "1"
    show_saved = request.args.get("saved") == "1"
    statuses = (
        "('hidden')"
        if show_hidden else
        "('summarized', 'liked', 'disliked')"
    )
    try:
        offset = max(0, int(request.args.get("offset", "0")))
    except ValueError:
        offset = 0
    feed_arg = request.args.get("feed", "").strip()
    feed_id = int(feed_arg) if feed_arg.isdigit() else None
    db = get_db()
    uid = current_user_id(db)
    declickbait = _declickbait(db)
    rows = art_repo.list_for_user(
        db, uid, hidden=show_hidden, saved=show_saved, feed_id=feed_id,
        sort=sort, topic=request.args.get("topic", "").strip() or None,
        limit=_PAGE_SIZE, offset=offset,
    )
    next_offset = offset + _PAGE_SIZE if len(rows) == _PAGE_SIZE else None
    next_qs = ""
    if next_offset is not None:
        parts = [f"sort={sort}", f"offset={next_offset}"]
        if show_hidden:
            parts.append("hidden=1")
        if show_saved:
            parts.append("saved=1")
        if feed_arg.isdigit():
            parts.append(f"feed={int(feed_arg)}")
        next_qs = "&".join(parts)
    return render_template(
        "_articles.html",
        articles=[_row_to_article(r, declickbait) for r in rows],
        next_qs=next_qs,
        is_first_page=(offset == 0),
    )


@bp.get("/search")
@auth.login_required
def search():
    """Full-text search over title/summary/full_text using FTS5."""
    q = request.args.get("q", "").strip()
    if not q:
        return render_template(
            "_articles.html", articles=[], next_qs="", is_first_page=True
        )
    db = get_db()
    uid = current_user_id(db)
    declickbait = _declickbait(db)
    try:
        rows = art_repo.search(db, uid, q, limit=_PAGE_SIZE)
    except Exception as exc:
        log.warning("Search failed for %r: %s", q, exc)
        rows = []
    return render_template(
        "_articles.html",
        articles=[_row_to_article(r, declickbait) for r in rows],
        next_qs="",
        is_first_page=True,
    )


@bp.post("/article/<int:article_id>/save")
@auth.login_required
def article_save(article_id: int):
    """Toggle the saved/read-later flag on an article and return the refreshed card."""
    db = get_db()
    uid = current_user_id(db)
    if not art_repo.exists(db, article_id):
        return Response("not found", status=404)
    art_repo.toggle_saved(db, uid, article_id)
    db.commit()
    card = art_repo.get_card(db, uid, article_id)
    return render_template("_article_card.html",
                           article=_row_to_article(card, _declickbait(db)))


@bp.post("/article/<int:article_id>/dismiss")
@auth.login_required
def article_dismiss(article_id: int):
    """Mark a single article as dismissed. Used by the swipe-left gesture."""
    db = get_db()
    uid = current_user_id(db)
    if not art_repo.exists(db, article_id):
        return Response("not found", status=404)
    art_repo.dismiss(db, uid, article_id)
    db.commit()
    return Response("", status=200)


@bp.post("/vote/<int:article_id>/<value>")
@auth.login_required
def vote(article_id: int, value: str):
    try:
        value = int(value)
    except ValueError:
        return Response("invalid vote", status=400)
    if value not in (1, -1):
        return Response("invalid vote", status=400)
    db = get_db()
    uid = current_user_id(db)
    if not art_repo.exists(db, article_id):
        return Response("not found", status=404)
    art_repo.record_vote(db, uid, article_id, value)
    db.commit()
    row = art_repo.get_card(db, uid, article_id)
    return render_template("_article_card.html",
                           article=_row_to_article(row, _declickbait(db)))


# ── Feed management ────────────────────────────────────────────────────────────

@bp.get("/sidebar/feeds")
@auth.login_required
def sidebar_feeds():
    """Feed list with per-feed unread + hidden + saved counts for the left sidebar.
    Feeds are grouped by tag; feeds with no tags appear under 'Untagged'."""
    db = get_db()
    uid = current_user_id(db)
    rows = art_repo.sidebar_counts(db, uid)
    total_unread = sum((r["unread"] or 0) for r in rows)
    total_hidden = sum((r["hidden"] or 0) for r in rows)
    total_saved = sum((r["saved"] or 0) for r in rows)

    by_tag: dict[str, list] = {}
    untagged: list = []
    for r in rows:
        tags = _split_tags(r["tags"])
        if not tags:
            untagged.append(r)
            continue
        for t in tags:
            by_tag.setdefault(t, []).append(r)
    tag_groups = [(tag, by_tag[tag]) for tag in sorted(by_tag.keys())]

    return render_template(
        "_sidebar_feeds.html",
        feeds=rows,
        tag_groups=tag_groups,
        untagged=untagged,
        total_unread=total_unread,
        total_hidden=total_hidden,
        total_saved=total_saved,
    )


@bp.get("/feeds")
@auth.admin_required
def feeds_list():
    db = get_db()
    return render_template("_feeds.html", feeds=_all_feeds(db),
                           extraction=_feed_extract_health(db))


@bp.post("/feeds")
@auth.admin_required
def feeds_add():
    url = request.form.get("url", "").strip()
    if not url:
        return Response("url required", status=400)
    db = get_db()
    res = db.execute(
        sql("INSERT INTO feeds (url) VALUES (:url) ON CONFLICT (url) DO NOTHING"),
        {"url": url},
    )
    if not res.rowcount:
        return Response("feed already exists", status=409)
    db.commit()
    return render_template("_feeds.html", feeds=_all_feeds(db))


@bp.get("/preferences")
@auth.login_required
def preferences_get():
    db = get_db()
    row = db.execute(sql(
        "SELECT profile_text, updated_at FROM preferences WHERE id=1"
    )).mappings().first()
    return render_template(
        "_preferences.html",
        profile_text=row["profile_text"] if row else "",
        updated_at=row["updated_at"] if row else None,
    )


@bp.post("/preferences")
@auth.admin_required
def preferences_save():
    text = request.form.get("profile_text", "").strip()
    db = get_db()
    db.execute(
        sql("""INSERT INTO preferences (id, profile_text, updated_at)
               VALUES (1, :profile, now())
               ON CONFLICT (id) DO UPDATE
                 SET profile_text = EXCLUDED.profile_text,
                     updated_at   = EXCLUDED.updated_at"""),
        {"profile": text},
    )
    db.commit()
    row = db.execute(sql(
        "SELECT profile_text, updated_at FROM preferences WHERE id=1"
    )).mappings().first()
    return render_template(
        "_preferences.html",
        profile_text=row["profile_text"],
        updated_at=row["updated_at"],
        saved=True,
    )


@bp.post("/preferences/regenerate")
@auth.admin_required
def preferences_regenerate():
    import threading
    from app.pipeline import regenerate_preferences

    app = current_app._get_current_object()

    def _run():
        try:
            regenerate_preferences(app)
        except Exception as exc:
            log.error("Manual preference regeneration failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
    return Response("ok", status=200)


@bp.get("/status")
@auth.login_required
def status():
    db = get_db()
    counts = {r["status"]: r["n"] for r in art_repo.status_counts(db)}
    last_poll = db.execute(sql(
        "SELECT MAX(last_polled_at) AS t FROM feeds"
    )).scalar()
    last_pipeline = get_setting(db, "last_pipeline_run_at", "") or None
    notify = []
    if get_setting(db, "notify_high_score", "") == "1":
        from app.pipeline import HIGH_SCORE_NOTIFY
        uid = current_user_id(db)
        rows = art_repo.high_score_unnotified(db, uid, HIGH_SCORE_NOTIFY)
        notify = [{"id": r["id"], "title": r["clean_title"] or r["title"],
                   "score": r["score"]} for r in rows]
        if notify:
            art_repo.mark_notified(db, uid, [n["id"] for n in notify])
            db.commit()
    feed_count = db.execute(sql("SELECT COUNT(*) FROM feeds")).scalar()
    wants_json = "application/json" in request.headers.get("Accept", "")
    if wants_json:
        from flask import jsonify
        return jsonify({
            "high_score": notify,
            "last_poll_at": last_poll,
            "last_pipeline_run_at": last_pipeline,
            "feed_count": feed_count,
            "article_counts": counts,
        })
    return render_template(
        "_status.html",
        last_poll=last_poll,
        last_pipeline=last_pipeline,
        feed_count=feed_count,
        counts=counts,
    )


def _ollama_form_state(db, **overrides) -> dict:
    """Values for _ollama_setting.html: saved settings, or the env default."""
    host = (get_setting(db, "ollama_host", "") or "").strip()
    port = (get_setting(db, "ollama_port", "") or "").strip()
    state = {
        "host": host,
        "port": port,
        "using_env": not (host and port),
        "env_base": ollama_client.OLLAMA_BASE,
        "active_base": ollama_base(db),
    }
    state.update(overrides)
    return state


@bp.get("/settings/ollama")
@auth.admin_required
def ollama_form():
    return render_template("_ollama_setting.html", **_ollama_form_state(get_db()))


@bp.post("/settings/ollama")
@auth.admin_required
def ollama_save():
    db = get_db()
    host = request.form.get("ollama_host", "").strip()
    port = request.form.get("ollama_port", "").strip()

    # Both blank is a deliberate "revert to the OLLAMA_HOST env var".
    if not host and not port:
        set_setting(db, "ollama_host", "")
        set_setting(db, "ollama_port", "")
        db.commit()
        return render_template(
            "_ollama_setting.html",
            **_ollama_form_state(db, saved=True,
                                 notice="Cleared — using the OLLAMA_HOST environment variable."),
        )

    try:
        base = ollama_client.compose_base_url(host, port)
    except ValueError as exc:
        return render_template(
            "_ollama_setting.html",
            **_ollama_form_state(db, host=host, port=port, error=str(exc)),
        )

    set_setting(db, "ollama_host", host)
    set_setting(db, "ollama_port", port)
    db.commit()
    log.info("Ollama endpoint set to %s", base)
    return render_template(
        "_ollama_setting.html",
        **_ollama_form_state(db, saved=True,
                             notice="Saved. Takes effect on the next pipeline run — no restart needed."),
    )


@bp.post("/settings/ollama/test")
@auth.admin_required
def ollama_test():
    """Probe the values currently in the form, without saving them."""
    db = get_db()
    host = request.form.get("ollama_host", "").strip()
    port = request.form.get("ollama_port", "").strip()

    if host or port:
        try:
            target = ollama_client.compose_base_url(host, port)
        except ValueError as exc:
            return render_template(
                "_ollama_setting.html",
                **_ollama_form_state(db, host=host, port=port, error=str(exc)),
            )
    else:
        target = ollama_client.OLLAMA_BASE

    ok, message, models = ollama_client.probe(target)
    return render_template(
        "_ollama_setting.html",
        **_ollama_form_state(db, host=host, port=port,
                             test_ok=ok, test_message=message, test_models=models),
    )


@bp.get("/settings/models")
@auth.admin_required
def models_form():
    db = get_db()
    installed = ollama_client.list_models(ollama_base(db))
    scoring = get_setting(db, "scoring_model", DEFAULT_SCORING_MODEL) or DEFAULT_SCORING_MODEL
    summary = get_setting(db, "summary_model", DEFAULT_SUMMARY_MODEL) or DEFAULT_SUMMARY_MODEL
    return render_template(
        "_models.html",
        installed=installed,
        scoring_model=scoring,
        summary_model=summary,
    )


@bp.get("/settings/titles")
@auth.admin_required
def titles_form():
    db = get_db()
    return render_template("_titles_setting.html", enabled=_declickbait(db))


@bp.post("/settings/titles")
@auth.admin_required
def titles_save():
    enabled = request.form.get("declickbait_enabled") == "1"
    db = get_db()
    set_setting(db, "declickbait_enabled", "1" if enabled else "")
    db.commit()
    return render_template("_titles_setting.html", enabled=enabled, saved=True)


@bp.get("/settings/content")
@auth.admin_required
def content_filter_form():
    db = get_db()
    return render_template(
        "_content_filter_setting.html",
        mode=_content_filter_mode(db),
        llm_enabled=get_setting(db, "content_filter_llm", "") == "1",
    )


@bp.post("/settings/content")
@auth.admin_required
def content_filter_save():
    mode = request.form.get("content_filter_mode", "")
    if mode not in content_filter.MODES:
        return Response("invalid mode", status=400)
    llm = request.form.get("content_filter_llm") == "1"
    db = get_db()
    set_setting(db, "content_filter_mode", mode)
    set_setting(db, "content_filter_llm", "1" if llm else "")
    db.commit()
    return render_template(
        "_content_filter_setting.html", mode=mode, llm_enabled=llm, saved=True
    )


@bp.get("/settings/retention")
@auth.admin_required
def retention_form():
    db = get_db()
    return render_template(
        "_retention_setting.html",
        days=retention.retention_days(db),
        confirmed=retention.is_confirmed(db),
        preview=retention.preview(db),
        users=_users_for_cleanup(db),
    )


def _users_for_cleanup(db):
    from app.models import users as U
    from sqlalchemy import select as _select
    return db.execute(
        _select(U.c.id, U.c.username).order_by(U.c.id)
    ).mappings().all()


@bp.post("/settings/retention")
@auth.admin_required
def retention_save():
    raw = request.form.get("retention_days", "").strip()
    try:
        days = int(raw)
    except ValueError:
        return Response("days must be a whole number", status=400)
    if days < 0:
        return Response("days must be 0 or more", status=400)
    db = get_db()
    set_setting(db, retention.SETTING_DAYS, str(days))
    retention.set_confirmed(db, request.form.get("retention_confirmed") == "1")
    db.commit()
    return render_template(
        "_retention_setting.html",
        days=days,
        confirmed=retention.is_confirmed(db),
        preview=retention.preview(db),
        users=_users_for_cleanup(db),
        saved=True,
    )


@bp.post("/settings/retention/prune")
@auth.admin_required
def retention_prune_now():
    """Run the policy immediately. Requires the confirmation toggle."""
    db = get_db()
    if not retention.is_confirmed(db):
        return Response("confirm the retention policy first", status=400)
    n = retention.prune(db)
    db.commit()
    return render_template(
        "_retention_setting.html",
        days=retention.retention_days(db),
        confirmed=True,
        preview=retention.preview(db),
        users=_users_for_cleanup(db),
        pruned=n,
    )


@bp.post("/settings/retention/clear-read")
@auth.admin_required
def retention_clear_read():
    """Remove read articles from selected users' lists (or all users)."""
    db = get_db()
    if request.form.get("all_users") == "1":
        ids = [u["id"] for u in _users_for_cleanup(db)]
    else:
        ids = [int(v) for v in request.form.getlist("user_id") if v.isdigit()]
    if not ids:
        return Response("select at least one user", status=400)
    n = retention.clear_read(db, ids)
    db.commit()
    return render_template(
        "_retention_setting.html",
        days=retention.retention_days(db),
        confirmed=retention.is_confirmed(db),
        preview=retention.preview(db),
        users=_users_for_cleanup(db),
        cleared=n,
    )


@bp.get("/insights")
@auth.admin_required
def insights_page():
    """Is the ranking any good? Measured against your votes."""
    db = get_db()
    from app.pipeline import SCORE_THRESHOLD
    current = float(get_setting(db, "score_threshold", str(SCORE_THRESHOLD))
                    or SCORE_THRESHOLD)
    return render_template(
        "insights.html",
        histogram=insights.score_histogram(db),
        threshold=current,
        agreement=insights.agreement(db, current),
        suggestion=insights.suggest_threshold(db),
        per_feed=insights.per_feed(db),
        per_topic=insights.per_topic(db),
        pipeline=insights.pipeline_health(db),
        runs=insights.recent_runs(db),
    )


@bp.post("/insights/threshold")
@auth.admin_required
def insights_apply_threshold():
    """A4: adopt the swept threshold in one click."""
    db = get_db()
    raw = request.form.get("threshold", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return Response("threshold must be a number", status=400)
    if not 0.0 <= value <= 1.0:
        return Response("threshold must be between 0.0 and 1.0", status=400)
    set_setting(db, "score_threshold", str(value))
    db.commit()
    return Response(f"threshold set to {value}", status=200)


@bp.get("/settings/notifications")
@auth.admin_required
def notifications_form():
    db = get_db()
    from app.pipeline import HIGH_SCORE_NOTIFY
    return render_template("_notifications_setting.html",
                           enabled=get_setting(db, "notify_high_score", "") == "1",
                           threshold=HIGH_SCORE_NOTIFY)


@bp.post("/settings/notifications")
@auth.admin_required
def notifications_save():
    db = get_db()
    enabled = request.form.get("notify_high_score") == "1"
    set_setting(db, "notify_high_score", "1" if enabled else "")
    db.commit()
    from app.pipeline import HIGH_SCORE_NOTIFY
    return render_template("_notifications_setting.html", enabled=enabled,
                           threshold=HIGH_SCORE_NOTIFY, saved=True)


@bp.get("/settings/topics")
@auth.admin_required
def topics_form():
    db = get_db()
    return render_template("_topics_setting.html", topics=topics_mod.counts(db))


@bp.post("/settings/topics")
@auth.admin_required
def topics_save():
    db = get_db()
    topic = request.form.get("topic", "").strip()
    action = request.form.get("action", "")
    try:
        if action == "clear":
            topics_mod.delete_rule(db, topic)
        elif action == "mute":
            topics_mod.set_rule(db, topic, muted=True)
        elif action == "renormalize":
            n = topics_mod.renormalize_all(db)
            db.commit()
            return render_template("_topics_setting.html",
                                   topics=topics_mod.counts(db),
                                   saved=True, renormalized=n)
        elif action in ("boost", "demote"):
            delta = 0.2 if action == "boost" else -0.2
            topics_mod.set_rule(db, topic, adjustment=delta)
        else:
            return Response("unknown action", status=400)
    except ValueError as exc:
        return render_template("_topics_setting.html", topics=topics_mod.counts(db),
                               error=str(exc))
    db.commit()
    return render_template("_topics_setting.html", topics=topics_mod.counts(db),
                           saved=True)


@bp.get("/settings/embeds")
@auth.admin_required
def embeds_form():
    db = get_db()
    enabled = get_setting(db, "embeds_enabled", "") == "1"
    return render_template("_embeds_setting.html", enabled=enabled)


@bp.post("/settings/embeds")
@auth.admin_required
def embeds_save():
    enabled = request.form.get("embeds_enabled") == "1"
    db = get_db()
    set_setting(db, "embeds_enabled", "1" if enabled else "")
    db.commit()
    return render_template("_embeds_setting.html", enabled=enabled, saved=True)


@bp.post("/settings/models")
@auth.admin_required
def models_save():
    scoring = request.form.get("scoring_model", "").strip()
    summary = request.form.get("summary_model", "").strip()
    if not scoring or not summary:
        return Response("both models required", status=400)
    db = get_db()
    set_setting(db, "scoring_model", scoring)
    set_setting(db, "summary_model", summary)
    db.commit()
    installed = ollama_client.list_models(ollama_base(db))
    return render_template(
        "_models.html",
        installed=installed,
        scoring_model=scoring,
        summary_model=summary,
        saved=True,
    )


@bp.get("/feeds/opml")
@auth.admin_required
def feeds_export_opml():
    db = get_db()
    rows = db.execute(sql("SELECT url, title FROM feeds ORDER BY id")).mappings().all()
    body = "\n".join(
        f'      <outline type="rss" text="{escape(r["title"] or r["url"])}" '
        f'title="{escape(r["title"] or r["url"])}" xmlUrl="{escape(r["url"])}"/>'
        for r in rows
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<opml version="2.0">\n'
        '  <head><title>Better Read feeds</title></head>\n'
        '  <body>\n'
        f'{body}\n'
        '  </body>\n'
        '</opml>\n'
    )
    return Response(
        xml,
        mimetype="text/x-opml",
        headers={"Content-Disposition": 'attachment; filename="feeds.opml"'},
    )


@bp.post("/feeds/opml")
@auth.admin_required
def feeds_import_opml():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return Response("file required", status=400)
    try:
        tree = ET.parse(upload.stream)
    except ET.ParseError as exc:
        return Response(f"invalid OPML: {exc}", status=400)
    urls = [
        outline.attrib["xmlUrl"].strip()
        for outline in tree.iter("outline")
        if outline.attrib.get("xmlUrl")
    ]
    if not urls:
        return Response("no feeds found in OPML", status=400)
    db = get_db()
    added = 0
    for url in urls:
        res = db.execute(
            sql("INSERT INTO feeds (url) VALUES (:url) ON CONFLICT (url) DO NOTHING"),
            {"url": url},
        )
        added += res.rowcount
    db.commit()
    return render_template("_feeds.html", feeds=_all_feeds(db), opml_added=added,
                           extraction=_feed_extract_health(db))


@bp.delete("/feeds/<int:feed_id>")
@auth.admin_required
def feeds_delete(feed_id: int):
    db = get_db()
    db.execute(sql("DELETE FROM feeds WHERE id=:id"), {"id": feed_id})
    db.commit()
    rows = _all_feeds(db)
    return render_template("_feeds.html", feeds=rows,
                           extraction=_feed_extract_health(db))


def _feed_extract_health(db) -> dict:
    return {r["id"]: r for r in extract.health_by_feed(db)}


def _all_feeds(db):
    return db.execute(sql(
        "SELECT id, url, title, last_polled_at, last_success_at, last_error, "
        "consecutive_failures, paused, score_threshold, tags "
        "FROM feeds ORDER BY id"
    )).mappings().all()


def _normalize_tags(raw: str) -> str:
    """Normalize a free-form tags string to canonical comma-separated form.
    Splits on commas, trims, lowercases, drops empties, dedupes, sorts.
    Returns '' for input that produces no tags."""
    if not raw:
        return ""
    seen: list[str] = []
    for part in raw.split(","):
        t = part.strip().lower()
        if t and t not in seen:
            seen.append(t)
    seen.sort()
    return ",".join(seen)


def _split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p for p in raw.split(",") if p]


@bp.post("/feeds/<int:feed_id>/pause")
@auth.admin_required
def feed_pause(feed_id: int):
    """Pause polling for a feed. Idempotent."""
    db = get_db()
    db.execute(sql("UPDATE feeds SET paused=true WHERE id=:id"), {"id": feed_id})
    db.commit()
    rows = _all_feeds(db)
    return render_template("_feeds.html", feeds=rows,
                           extraction=_feed_extract_health(db))


@bp.post("/feeds/<int:feed_id>/resume")
@auth.admin_required
def feed_resume(feed_id: int):
    """Resume polling for a feed and reset its failure counter."""
    db = get_db()
    db.execute(
        sql("UPDATE feeds SET paused=false, consecutive_failures=0, "
            "last_error=NULL WHERE id=:id"),
        {"id": feed_id},
    )
    db.commit()
    rows = _all_feeds(db)
    return render_template("_feeds.html", feeds=rows,
                           extraction=_feed_extract_health(db))


@bp.post("/feeds/<int:feed_id>/threshold")
@auth.admin_required
def feed_set_threshold(feed_id: int):
    """Set per-feed score threshold. Empty string clears the override."""
    raw = request.form.get("score_threshold", "").strip()
    db = get_db()
    if raw == "":
        db.execute(sql("UPDATE feeds SET score_threshold=NULL WHERE id=:id"), {"id": feed_id})
    else:
        try:
            value = float(raw)
        except ValueError:
            return Response("threshold must be a number 0.0-1.0", status=400)
        if not 0.0 <= value <= 1.0:
            return Response("threshold must be 0.0-1.0", status=400)
        db.execute(
            sql("UPDATE feeds SET score_threshold=:v WHERE id=:id"),
            {"v": value, "id": feed_id},
        )
    db.commit()
    rows = _all_feeds(db)
    return render_template("_feeds.html", feeds=rows,
                           extraction=_feed_extract_health(db))


@bp.post("/feeds/<int:feed_id>/tags")
@auth.admin_required
def feed_set_tags(feed_id: int):
    """Set comma-separated tags on a feed. Empty string clears all tags."""
    raw = request.form.get("tags", "")
    normalized = _normalize_tags(raw)
    db = get_db()
    db.execute(
        sql("UPDATE feeds SET tags=:tags WHERE id=:id"),
        {"tags": normalized or None, "id": feed_id},
    )
    db.commit()
    rows = _all_feeds(db)
    return render_template("_feeds.html", feeds=rows,
                           extraction=_feed_extract_health(db))


# ── Article reader ─────────────────────────────────────────────────────────────

@bp.get("/article/<int:article_id>/content")
@auth.login_required
def article_content(article_id: int):
    db = get_db()
    row = db.execute(sql(
        "SELECT title, url, full_text, raw_snippet, feed_content, clean_title, "
        "title_was_clickbait, aside_spans "
        "FROM articles WHERE id=:id"),
        {"id": article_id},
    ).mappings().first()
    if not row:
        return Response("Article not found.", status=404)
    art_repo.mark_read(db, current_user_id(db), article_id)
    db.commit()
    description = (row["raw_snippet"] or "").strip()
    full_text = row["full_text"] or row["feed_content"] or ""
    # Strip against the stored title — that's the wording the body may duplicate,
    # regardless of which title is displayed.
    content = _clean_content(full_text, title=row["title"], description=description)
    embeds_enabled = get_setting(db, "embeds_enabled", "") == "1"
    title, original_title = _resolve_title(dict(row), _declickbait(db))
    mode = _content_filter_mode(db)
    groups, aside_count = _content_blocks(
        content, embeds_enabled, mode,
        row["aside_spans"],
    )
    return render_template(
        "_article_content.html",
        title=title,
        original_title=original_title,
        description=description,
        groups=groups,
        filter_mode=mode,
        aside_count=aside_count,
    )


@bp.get("/export/markdown")
@auth.login_required
def export_markdown():
    """Your reading, as Markdown files. Scoped to the calling user."""
    db = get_db()
    scope = request.args.get("scope", "saved")
    if scope not in export_mod.SCOPES:
        return Response("scope must be saved, liked or all", status=400)
    data, n = export_mod.build_zip(db, current_user_id(db), scope)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    log.info("Exported %d articles (scope=%s)", n, scope)
    return Response(
        data, mimetype="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="betterread-{scope}-{stamp}.zip"'},
    )


@bp.get("/digest")
@auth.login_required
def digest_fragment():
    """What you missed: everything unread, grouped into themes.

    Uses the cached copy unless the unread set has changed, so opening the page
    repeatedly does not cost repeated Ollama calls.
    """
    db = get_db()
    uid = current_user_id(db)
    from app.pipeline import _summary_model, ollama_base
    body, count, from_cache = digest_mod.generate(
        db, uid, model=_summary_model(db), base_url=ollama_base(db),
        force=request.args.get("force") == "1",
    )
    db.commit()
    known = {r["id"]: r["url"] for r in digest_mod.unread_for(db, uid)}
    return render_template(
        "_digest.html",
        body=digest_mod.linkify(body, known) if body else None,
        count=count, from_cache=from_cache,
        made_at=(digest_mod.cached(db, uid) or {}).get("created_at"),
    )


@bp.post("/digest/dismiss")
@auth.login_required
def digest_dismiss():
    db = get_db()
    digest_mod.clear(db, current_user_id(db))
    db.commit()
    return Response("", status=200)


@bp.get("/health")
def healthcheck():
    """Liveness *and* ingestion. Public: the container healthcheck calls it.

    Returning 200 while nothing has been ingested for weeks is how the June
    outage stayed invisible.
    """
    db = get_db()
    st = health.ingestion_status(db)
    body = {
        "status": "ok" if st["healthy"] else "degraded",
        "feeds_total": st["total"],
        "feeds_paused": st["paused"],
        "last_success_at": st["last_success_at"].isoformat() if st["last_success_at"] else None,
        "ingestion_stale": st["stale"],
    }
    from flask import jsonify
    return jsonify(body), (200 if st["healthy"] else 503)


@bp.get("/count")
@auth.login_required
def article_count():
    db = get_db()
    return str(art_repo.unread_count(db, current_user_id(db)))


# ── Manual triggers ────────────────────────────────────────────────────────────

@bp.post("/poll")
@auth.admin_required
def manual_poll():
    import threading
    from app.feeds import poll_all_feeds
    from app.pipeline import run_pipeline

    app = current_app._get_current_object()

    def _run():
        try:
            poll_all_feeds(app)
            run_pipeline(app)
        except Exception as exc:
            log.error("Manual poll failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
    return Response("ok", status=200)


@bp.post("/dismiss-all")
@auth.login_required
def dismiss_all():
    """Mark every currently-listed article (summarized/liked/disliked) as
    'dismissed' so they disappear from the main view. Respects the current
    feed filter when ?feed=<id> is provided. Votes remain in the votes table
    so the preference signal is preserved."""
    db = get_db()
    feed_arg = request.args.get("feed", "").strip()
    feed_id = int(feed_arg) if feed_arg.isdigit() else None
    n = art_repo.dismiss_all(db, current_user_id(db), feed_id)
    db.commit()
    return Response(f"dismissed {n} articles", status=200)


@bp.post("/rescore-hidden")
@auth.admin_required
def rescore_hidden():
    """Reset all hidden articles to 'new' so the next pipeline run re-scores them
    against the current preference profile."""
    import threading
    from app.pipeline import run_pipeline

    db = get_db()
    n = art_repo.rescore_hidden(db)
    db.commit()

    app = current_app._get_current_object()

    def _run():
        try:
            run_pipeline(app)
        except Exception as exc:
            log.error("Rescore failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
    return Response(f"requeued {n} articles", status=200)

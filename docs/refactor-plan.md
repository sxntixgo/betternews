# Better News — Presenter extraction and view split

> **✅ Completed — historical.** Presenter extraction and the view split both
> shipped: `app/presenters.py` exists and is guarded by `tests/test_presenters.py`,
> which asserts it imports no Flask. Kept as a record of the reasoning.

Preparation for a second client. Both steps are worth doing on their own merits;
neither commits us to the mobile app, and neither changes a single URL.

| Step | What | Size | Why now |
|---|---|---|---|
| **Step 1** | Lift the presenter layer out of `routes.py` into `app/presenters.py` | M | The actual precondition for a second client |
| **Step 2** | Split the remaining routes into an `app/views/` package | M | `routes.py` is 1,534 lines and 25% of the Python; makes the slot for `api` |

Done in this order deliberately. Step 1 moves the top 227 lines out; Step 2 then
carves up what is left. Reversing them means moving the same helpers twice.

---

## The measurements this plan rests on

```
app/routes.py            1,534 lines   69 routes   917 statements (25% of app/)
  lines   1–227          imports, 4 regex constants, 10 presenter helpers
  lines 229–1534         the 69 routes
templates/               31 files, 2,100 lines
render_template : jsonify         63 : 4
```

Coupling into `routes.py` is almost nil, which is what makes this safe:

| From | What | Count |
|---|---|---|
| `app/__init__.py:61` | `from app.routes import bp` | 1 |
| `tests/test_routes.py` | `from app.routes import _<helper>` | ~30 |
| everything else | — | 0 |

No other app module imports from `routes.py`. Templates reference endpoints as
`url_for('main.…')` in **9** places.

---

## Framing — what "separate the frontend" actually means here

The presenter helpers are not formatting. They decide *what the reader sees*:

| Helper | Decision it makes |
|---|---|
| `_resolve_title` | which headline — the rewrite or the original |
| `_row_to_article` | the row → card mapping every list goes through |
| `_clean_content` | drops a body line duplicating the title |
| `_to_blocks` / `_group_blocks` / `_content_blocks` | which passages fold as older-news padding |
| `_extract_reading_time` | the 🕐 estimate |
| `_declickbait` / `_content_filter_mode` | the settings the above read |

A mobile client either reimplements these — and drifts, so the phone shows a
clickbait headline the web hid — or receives raw rows and renders differently.
While they are private helpers of the HTML layer, there is no way to serve a
second client honestly. That is the whole argument for Step 1.

---

## Step 1 — `app/presenters.py`  ·  **Sonnet**-led

Lines 1–227 of `routes.py` are already exactly this layer, in one contiguous
block, ending at the `# ── Accounts ──` divider on line 229. The seam exists;
this step only names it.

### 1.1 Move the block  ·  **Sonnet**

New `app/presenters.py` takes, unchanged:

```
_READ_TIME_RE  _BULLET_RE  _TWITTER_URL_RE  _INSTAGRAM_URL_RE
_embed_match          _extract_reading_time   _clean_content
_to_blocks            _group_blocks           _content_blocks
_content_filter_mode  _row_to_article         _declickbait
_resolve_title
```

Drop the leading underscore on the ten helpers: they stop being private the
moment they live in a module whose purpose is to be imported. `routes.py` gets
`from app.presenters import ...`.

Two of them read settings rather than shape data — `declickbait(db)` and
`content_filter_mode(db)`. They belong here anyway: they are the inputs the
other presenters take, and a JSON serializer needs the same values.

**Do not** redesign anything while moving. No signature changes, no
consolidation, no "while I'm here". A pure move is reviewable by diffing the
function bodies; anything else is not.

### 1.2 Repoint the tests  ·  **Haiku**

~30 `from app.routes import _x` → `from app.presenters import x`. Mechanical.
The tests themselves do not change — that is the point of doing 1.1 as a pure
move.

### 1.3 Prove the seam is real  ·  **Sonnet**

The move is only worth something if the layer is genuinely independent. One new
test asserts it:

```python
def test_presenters_do_not_import_flask():
    """A second client cannot use a layer that needs a request context."""
    import app.presenters as p
    src = inspect.getsource(p)
    assert "from flask" not in src and "import flask" not in src
    assert "request" not in src
```

If that fails, the extraction is incomplete and Step 2 will inherit the problem.

**Already verified — all ten are Flask-free today.** Walking each function's AST
for references to `request`, `g`, `session`, `current_app`, `render_template`,
`url_for` and `Response` returns nothing for every one of them:

```
_embed_match  _extract_reading_time  _clean_content  _to_blocks  _group_blocks
_content_blocks  _content_filter_mode  _row_to_article  _declickbait
_resolve_title          → flask deps: none
```

So Step 1 is a pure move: **no signature changes, no parameterising, nothing to
untangle.** The layer already exists and has simply been living in the wrong
file. The test above locks that property in rather than establishing it — which
is the useful kind of test to add during a refactor, and the reason to add it
now rather than after Step 2 muddies the water.

### Done when

- `app/presenters.py` exists, `routes.py` starts at its first route
- 987 tests green, `app/` coverage still 100%
- the no-Flask test passes
- **no URL, template, or behaviour has changed** — `git diff` on `templates/` is empty

---

## Step 2 — `app/views/` package  ·  **Opus** (structure) → **Sonnet** (moves)

### 2.1 The blueprint decision  ★ read this one  ·  **Opus**

**One blueprint, several modules.** Not one blueprint per module.

Splitting into `auth_bp`, `settings_bp`, … renames every endpoint
(`main.login` → `auth.login`), which touches the 9 `url_for('main.…')` call
sites and every `redirect(url_for(...))` in the auth flow. That is churn bought
with nothing: the benefit sought here is file size, and file size does not
require a second `Blueprint` object.

```python
# app/views/__init__.py
from flask import Blueprint

bp = Blueprint("main", __name__)          # same name, same endpoints

# Imported for their side effect: each module registers routes on `bp`.
# Must come after bp exists, hence the position — this is the one place in
# the codebase where import order is load-bearing, so it is commented as such.
from app.views import (accounts, admin, feeds, ops, reading, settings)  # noqa: E402,F401
```

`app/__init__.py` changes one line: `from app.views import bp`.

The future `api` blueprint **is** separate — `Blueprint("api", url_prefix="/api/v1")` —
because there the endpoint namespace and the URL prefix are both wanted. That is
the case a second blueprint earns; this one is not.

### 2.2 The six modules  ·  **Sonnet**, one commit each

Line ranges from the current file. Move in this order — smallest and most
isolated first, so the pattern is established before the big one:

| # | Module | Routes | Lines now | Contents |
|---|---|---|---|---|
| 1 | `views/admin.py` | 4 | 385–456 | user list, reset-password, role, delete |
| 2 | `views/accounts.py` | 9 | 229–384 | login, register, logout, profile, topics, password |
| 3 | `views/ops.py` | 11 | 727–780, 993–1091, 1449–1533 | status, health, count, poll, insights, ollama-log, rescore-hidden |
| 4 | `views/feeds.py` | 11 | 611–669, 1187–1358 | sidebar, feed CRUD, OPML, pause/resume/threshold/tags |
| 5 | `views/reading.py` | 13 | 457–610, 1359–1448 | index, articles, search, save, dismiss, vote, content, digest, export, dismiss-all |
| 6 | `views/settings.py` | 21 | 670–726, 781–992, 1032–1053, 1093–1186 | every `/settings/*`, preferences, models, retention, notifications, topics, embeds |

Named `accounts.py`, not `auth.py` — `app/auth.py` already exists and holds the
actual session and decorator logic. Two files named `auth` in one import graph
is a bug waiting for a tired evening.

Each commit: move the routes, move only the helpers used by *just* that module
(`_users_fragment` → admin, `_ollama_form_state` → settings, `_all_feeds` /
`_normalize_tags` / `_split_tags` → feeds), run the suite, done. Anything used
by two modules stays in `presenters.py` or moves to the module that owns the
concept — decide per case, do not create a `views/helpers.py`, which is where
this kind of refactor goes to die.

### 2.3 Retire `routes.py`  ·  **Haiku**

Delete it outright rather than leaving a re-export shim. The only importer is
`app/__init__.py`, already updated in 2.1, and `tests/test_routes.py` imports
only presenters, already repointed in 1.2. A shim would be permanent.

`tests/test_routes.py` (1,812 lines) can stay one file — it tests behaviour
through the client, not modules, and splitting it is a separate decision with
its own risk. Note it and move on.

### 2.4 Docs  ·  **Haiku**

`CLAUDE.md` names `app/routes.py` in its Key Files list and describes it as
"HTMX-first: most return HTML fragments". Replace with `app/views/` and
`app/presenters.py`, and state the rule the split encodes: **a view function
decides what to fetch and which template to render; anything deciding what the
reader sees belongs in `presenters.py`, because a second client will need it.**

---

## Verification, both steps  ·  **Sonnet**

1. 987 tests green, `app/` coverage 100% — after *every* commit, not just at the end
2. `git diff --stat templates/ static/` is empty across the whole refactor
3. Route table identical before and after:
   ```
   docker compose exec -T web python -c "
from app import create_app
for r in sorted(create_app().url_map.iter_rules(), key=str):
    print(r.endpoint, sorted(r.methods - {'HEAD','OPTIONS'}), r.rule)" > after.txt
   diff before.txt after.txt
   ```
   Capture `before.txt` first — **71 rules** today. This is the real safety
   net: same URLs, same endpoint names, same methods.
4. Browser smoke on the local stack — list, vote, open an article, settings,
   sidebar. The suite covers these, but the suite also passed while a stray
   `hx-get` was refetching the list on every click.

## What this explicitly does not do

- No new services, containers, or build step
- No JSON API. Endpoint design waits until the mobile app's screens are known;
  invented-early endpoints get thrown away
- No token auth — that lands with the app, as a table and a second path in
  `@login_required`
- No pagination change. Cursor paging matters for a syncing client and is
  tracked separately; mixing it into a pure refactor would make the diff
  unreviewable

## Sequencing note

Step 1 is independently valuable and low risk — it can ship alone. Step 2 is
worth doing whether or not the mobile app happens, but it is the larger diff;
if only one gets done, do Step 1.

| Model | Tasks |
|---|---|
| **Opus** | 2.1 blueprint structure |
| **Sonnet** | 1.1, 1.3, 2.2 (×6), verification |
| **Haiku** | 1.2, 2.3, 2.4 |

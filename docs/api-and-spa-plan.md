# Better News — pagination, API, SPA

> **⚠️ Outdated — parts of this are now wrong.** The pagination and API work
> shipped, but **§B.4 was reversed**: it said settings, admin and insights would
> never be ported to the API, and they since were — the API now covers
> everything (see `CLAUDE.md`). Kept as a record, but do not treat any statement
> here as current.

Three phases, in the order they must happen. Each is useful on its own; each is
a precondition for the next.

| Phase | What | Size | Blocks |
|---|---|---|---|
| **A** | Collapse duplicates in SQL so pagination is exact | M | everything that syncs |
| **B** | `/api/v1` + token auth, serving the existing UI's needs | L | the SPA and the phone |
| **C** | SPA replacing the HTMX reading UI | L+ | — |

Phase A is a bug fix you want regardless. Phase B is additive — the browser UI
keeps working throughout. Phase C is the only one that removes anything, and it
is deliberately scoped to the reading experience rather than all 70 routes.

---

## Where we start from

Two pieces of groundwork are already done and this plan depends on both:

- `app/presenters.py` — the ten decisions both clients must agree on (which
  headline after de-clickbait, which passages fold as padding, reading time).
  Provably free of Flask and request context, enforced by `tests/test_presenters.py`.
- `app/views/` — six modules on one blueprint, leaving the slot for a second.

```
routes        70 across 6 modules      render_template 68 : jsonify 4
frontend      31 templates, 2,125 lines; 628 lines of inline JS; 990 lines CSS
auth          session cookies only — 0 occurrences of bearer/token, no token table
```

`ops.py:39` already varies on `Accept`, which is the one precedent for
content negotiation in the codebase — and Phase B deliberately does *not*
follow it. See B.1.

---

## Phase A — collapse in SQL  ·  **Opus** (query) → **Sonnet** (rest)

### The bug, precisely

`_collapse_clusters` keeps the best member of each duplicate cluster in Python,
over a window of `limit * OVER_FETCH` rows. Two consequences:

1. Filling a 50-row page can read 60 source rows, so `offset + limit` restarted
   the next page *inside* the previous one. **Fixed** — the offset now advances
   by rows consumed.
2. A cluster whose copies straddle the page boundary is emitted **again** on the
   next page, because page two starts with an empty seen-map. **Not fixed.** It
   is a strict `xfail` in `tests/test_dedupe.py`.

A browser reader scrolling once barely notices (2). A phone doing infinite
scroll and background sync shows duplicate cards routinely.

### A.1 The query  ★ the whole phase is this  ·  **Opus**

Collapse in Postgres so `LIMIT`/`OFFSET` applies to already-collapsed rows:

```sql
SELECT DISTINCT ON (COALESCE(cluster_id, id::text)) ...
```

Three things make this harder than it looks, and getting any of them wrong is
worse than the bug:

- **`DISTINCT ON` dictates the leading `ORDER BY`.** It must lead with the
  cluster key, but the list orders by `published_at DESC` or by
  `effective_score DESC`. So: an inner query picking the winner per cluster,
  then an outer query ordering and paginating.
- **`duplicate_count` is currently a side effect of the Python loop.** It
  becomes `COUNT(*) OVER (PARTITION BY cluster_key) - 1` in the inner query.
- **`cluster_id` is nullable**, and every NULL must stay its own row rather than
  collapsing into one giant "no cluster" group — hence the `COALESCE` above.
  This is the mistake to write the test for first.

`effective_score` includes the per-user topic boost (`BOOST_SQL`), so the
winner-picking is user-dependent. Verify the boost still applies after the
rewrite; a plain "highest score in cluster" would quietly ignore it.

### A.2 Tests  ·  **Sonnet**

Flip the existing `xfail` to a passing test — that is the acceptance criterion.
Add: NULL cluster_ids stay separate; `duplicate_count` matches the old Python
result for the same fixtures; paging 200 articles in pages of 10 yields 200
distinct ids and no repeats; the topic boost still reorders.

### A.3 Verify against real data  ·  **Sonnet**

Compare old and new against the 17k-article corpus before trusting it: same
ids in the same order for page 1, and the full page-through yields no
duplicates. A query rewrite that passes fixtures and reorders the live list is
not a success.

### Done when

The `xfail` passes as a normal test, page-through of the real corpus is
duplicate-free, and `/articles` is not measurably slower (add an index on
`cluster_id` if it is — one already exists).

---

## Phase B — `/api/v1`  ·  **Opus** (shape, auth) → **Sonnet** (endpoints)

The browser UI keeps working untouched throughout this phase. Nothing here
removes anything.

### B.1 Shape  ★ read this one  ·  **Opus**

**A separate blueprint, not content negotiation.** `ops.py:39` varies on
`Accept` and that is exactly the pattern not to spread: it couples the two
representations in one function, so every change risks the other client, and
the HTML path's session assumptions leak into the JSON path. A second blueprint
is what earns itself here — the URL prefix and the endpoint namespace are both
wanted:

```python
api = Blueprint("api", __name__, url_prefix="/api/v1")
```

Rules the endpoints follow:

- **Serialization goes through `app/presenters.py`.** A JSON article is
  `row_to_article(...)` plus a serializer — never a raw row. This is the entire
  reason that module exists; if the API reaches past it, the phone and the
  browser will disagree about headlines within a month.
- **Versioned from the first commit.** `/api/v1` costs nothing now and is
  impossible to retrofit once a phone in someone's pocket depends on it.
- **Errors are JSON**, always, including 401/403/404 — an HTML error page is
  what a native client cannot parse and will report as a crash.

### B.2 Token auth  ·  **Opus**

Session cookies do not suit a native client. Needed:

- `api_tokens` table: `id`, `user_id`, `token_hash`, `name`, `created_at`,
  `last_used_at`, `revoked_at`. **Hash the token** — it is a password.
- Issue and revoke from the profile page, per device, showing the value once.
- `@api_auth` reading `Authorization: Bearer`, resolving to a user, updating
  `last_used_at`. Do **not** extend `@login_required` to accept both: one
  decorator serving two auth models is how a session-fixation bug gets written.
- `tests/test_auth.py` already asserts a plain user gets 403 from every admin
  route. Mirror that for the API — every token-authenticated route, checked.

### B.3 Endpoints  ·  **Sonnet**

Scope to what a reading client needs. Not all 70 routes.

| Endpoint | Notes |
|---|---|
| `GET /articles` | cursor-paginated (Phase A), filters mirror `list_for_user` |
| `GET /articles/<id>` | full text, with `content_blocks` already applied |
| `POST /articles/<id>/vote` `…/save` `…/dismiss` `…/read` | per-user state |
| `GET /feeds` | for the sidebar |
| `GET /digest` | "what you missed" |
| `GET /topics` `POST /topics/<t>/stance` | per-user stances |
| `GET /sync?since=` | **the one to design carefully** — see below |

`/sync` is what makes a phone feel native: per-user state changed since a
timestamp, so the app reconciles rather than refetching. It is also the easiest
to get wrong. Defer it until the app has screens; a guessed sync protocol is
worse than none.

### B.4 Settings, admin, insights stay server-rendered  ·  **Opus** (decision)

24 settings routes, 4 admin, 9 ops — 37 of the 70 — are low-traffic panels used
from a desktop browser. Porting them to JSON *and* rebuilding them in the SPA is
weeks of work for screens visited monthly. They stay as they are, and Phase C
does not touch them.

State this in `CLAUDE.md` so it is a decision rather than an omission.

### Done when

A script can authenticate with a token, list articles, open one, vote, and see
the vote reflected — with the browser UI still passing its full suite unchanged.

---

## Phase C — the SPA  ·  **Opus** (scope, build) → **Sonnet** (screens)

Scoped to the **reading experience**: list, reader, digest, topics, feeds
sidebar. Settings and admin remain server-rendered pages the SPA links out to.

### C.1 What has to be rebuilt, honestly  ·  **Opus**

628 lines of inline JS in `index.html` and `base.html` are not scaffolding —
they are features, and each needs a deliberate decision to port or drop:

| | |
|---|---|
| reader modal | `<dialog>`, lazy Twitter/Instagram embed hydration |
| swipe gestures | swipe-right like, swipe-left dismiss, pull-to-refresh |
| keyboard nav | `j`/`k`/`l`/`o`/`r` |
| favicon badge | canvas-drawn unread count, PWA `setAppBadge` |
| notifications | high-score alerts, permission-on-first-click |
| infinite scroll | `hx-trigger="revealed"` sentinel |
| theme | light/dark, persisted, redraws the favicon |
| digest panel | dismissable, links into articles |

Plus 990 lines of CSS, which should be **carried over rather than rewritten** —
it is the one part of the frontend with no logic in it.

### C.2 Stack  ·  **Opus**

Match `job-application-tracker`: React + Vite + TypeScript, Playwright e2e. Not
because it is better, but because it is the stack already in the home stack, and
one toolchain across two apps is worth more than a marginally better choice in
each.

New in this repo and worth costing honestly: a build step, `node_modules`
(~134 MB in the tracker), a second test runner, and a second container behind
Caddy.

### C.3 Order  ·  **Sonnet**, one screen per commit

1. Shell: routing, token storage, auth guard
2. Article list — the whole point; cursor pagination and infinite scroll
3. Reader
4. Sidebar: feeds, saved, hidden
5. Digest and topic stances
6. Gestures, keyboard, badge, notifications

### C.4 Cut over  ·  **Opus**

Run both until the SPA reaches parity on the six screens above: Caddy serves
the SPA at `/app`, HTMX stays at `/`. Then flip the root and **delete the HTMX
reading templates** — not before, and not "temporarily", which is how two
frontends become permanent.

`templates/` does not empty out: settings, admin, insights, login and the error
pages stay. Expect roughly half of the 31 templates to remain.

### Done when

The SPA covers the six screens, the HTMX reading UI is deleted, and the
remaining server-rendered pages still pass their tests.

---

## Sequencing and risk

Phase A ships alone and improves the app today. Phase B is additive — if it
stalls, nothing is worse than before. Phase C is the only irreversible one, and
C.4 is where it becomes irreversible; everything before that can be abandoned
with a deleted directory.

The honest risk in C: the HTMX UI is 628 lines of JS that took months of
bug-fixing to get right — the scroll bug, the vote refetch, the theme-toggle
null. A rewrite re-earns all of that. Budget for rediscovering bugs you have
already fixed once.

## Model assignments

| Model | Activities |
|---|---|
| **Opus** | A.1 query rewrite · B.1 API shape · B.2 token auth · B.4 scope decision · C.1 port inventory · C.2 stack · C.4 cut-over |
| **Sonnet** | A.2 tests · A.3 real-data verification · B.3 endpoints · C.3 screens |
| **Haiku** | doc updates in `CLAUDE.md` after each phase |

Opus gets the four decisions that are expensive to reverse: a query everything
reads, an auth model, the API's shape, and when to delete the old frontend.

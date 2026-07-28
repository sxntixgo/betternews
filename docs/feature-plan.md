# Better News — New Feature Plan

> Successor to `docs/improvements-next.md`. Every item in that file is shipped
> except *"Notification when a high-score article (≥0.8) lands"* (carried here as
> B3), so this plan covers new ground.

Written against commit `b8a53f1` (`main`). Each task carries a recommended model —
**Haiku** / **Sonnet** / **Opus** — extending the convention from
`docs/plan.md` §"Task List & Recommended Models". See
[Summary — task list with model assignment](#summary--task-list-with-model-assignment).

**Phases 0–4 are your explicit requests.** **Tracks A–D are proposed**, ordered by
leverage — a menu, not a commitment.

| | | |
|---|---|---|
| **Phase −1** | **Restore service — the app is broken right now** | **S** |
| **Phase 0** | Postgres migration + data layer + retention/favorites | L+ |
| **Phase 1** | Accounts, roles, per-user state | L+ |
| **Phase 2** | Ollama host/port in Settings | S–M |
| **Phase 3** | De-clickbait titles | M |
| **Phase 4** | Strip / frame irrelevant article sections | M–L |
| *Track A* | *Ranking directability (topics, dedupe, insights)* | |
| *Track B* | *Speed and trust (batching, observability, notifications)* | |
| *Track C* | *Ingestion reach (extraction, YouTube, newsletters)* | |
| *Track D* | *Reading experience (digest, offline, export)* | |

**Decisions made:**
- **Database: migrate to Postgres, data layer included.** Recorded honestly: at
  17,093 articles / 116 MB / `--workers 1`, SQLite is not near its limits, and I
  said so. Your call, and there are real wins below (generated-column search,
  cross-process locking, multi-worker capability). Planned properly rather than
  half-heartedly.
- **Multi-tenancy: per-user read state, shared ranking.** Feeds, articles, scores
  and the preference profile stay global; each user gets their own read/saved
  state and votes. Ollama cost is unchanged by user count.
- **Registration: open, first account becomes admin.**

**Phase 0 must precede Phase 1.** Building multi-user on SQLite and then porting
means doing the hardest migration in this plan twice.

---

## Phase −1 — The app is currently broken. Fix this first.  ·  **Haiku** + **Sonnet**

Diagnosed live on 2026-07-25, before any of the work below is worth starting.
`rss-reader-web-1` reports **"Up 3 weeks (healthy)"** — the healthcheck only pings
`localhost:5000/`, so it has never noticed either failure.

**Symptom:** no new articles since **2026-06-12** (43 days). 9,133 of 17,093
articles — 53% — are stuck in `status='new'`, never scored.

**Two independent causes:**

| | Cause | Evidence | Fix |
|---|---|---|---|
| **A** | All 3 feeds **auto-paused** and never recovered | `paused=1`, `consecutive_failures=5` on every feed; `last_error` = `urlopen error [Errno -2] Name or service not known` at `2026-06-12T22:10` | Resume the feeds |
| **B** | **Ollama is unreachable** | `10.0.10.207:11434` → `ConnectError: [Errno 111] Connection refused` | Start Ollama; bind `OLLAMA_HOST=0.0.0.0:11434` |

**A is the more interesting failure.** DNS inside the container resolves fine
*today* (`www.theverge.com → 151.101.1.91`), so the June DNS errors were transient.
But `AUTO_PAUSE_AFTER_FAILURES = 5` paused all three feeds and **there is no
auto-recovery** — a brief network blip six weeks ago permanently silenced every
source, and nothing ever retried. See the new item −1.1.

**B explains the 9,133 backlog.** `generate()` returns `None` on failure and callers
skip the article (`pipeline.py:83-85`), so every scoring attempt has been a silent
no-op. The pipeline itself is still running — `last_pipeline_run_at` is today.

Also check once Ollama is back: `settings` holds
`scoring_model = summary_model = ministral-3:14b`, while `.env` says `llama3.1:8b`.
**The settings row wins** (`pipeline.py:27`), so the env value is ignored — confirm
that model actually exists on the server, or every call will keep failing.

### −1.1 Auto-paused feeds must auto-recover  *(new — this outage is the argument)*  ·  **Sonnet**

Today auto-pause is terminal: it requires someone to notice and click Resume. Add a
scheduled retry that re-probes paused feeds on a backoff (hourly, then daily),
clearing the pause on a success. Optionally surface "3 feeds paused" in the header
— the current failure was invisible from the UI for six weeks.

**Effort:** S. **Risk:** low. **Value: highest in this document**, because it is the
difference between a transient blip and a dead reader.

### −1.2 Health check should reflect ingestion  ·  **Haiku**

The Docker healthcheck (`docker-compose.yml`) only verifies Flask answers. Make it —
or `/status` — report unhealthy when no feed has succeeded in N intervals. A
container reporting "healthy" for three weeks while ingesting nothing is a
monitoring failure, not just a feed failure.

**Effort:** S. **Risk:** low.

---

## Framing

**1. `articles.status` conflates two things.** From `schema.sql`:

```
new | scored | hidden | summarized | liked | disliked | dismissed
└──────── pipeline lifecycle ──────┘ └──── user opinion ────┘
```

`new → scored → summarized` is where the *article* is. `liked | disliked |
dismissed` is what *a person* thinks. Harmless with one user; with two it's a bug —
your dismiss removes the article from everyone's list. Splitting it is Phase 1.2.

**2. The current migration mechanism can't express Phase 1.** `db.py:53-57` is a
hand-rolled list of additive `ALTER TABLE`s wrapped in `except Exception: pass`.
No version tracking, no ordering, no rollback, no data backfill — and a migration
failing for a *real* reason (lock, disk, typo) leaves a silently broken schema.
Phase 0 replaces it with Alembic.

**3. `docker-compose.yml:5` publishes `"5001:5000"`** — binds `0.0.0.0`, the whole
LAN, on an app with no auth today (`grep -rniE "login|password|session\[" app/
templates/` → nothing). Fixed in Phase 1.1.

---

## Phase 0 — Postgres migration and data layer  *(requested)*  ·  **Opus**-led

### 0.1 Stack  ·  **Sonnet**

| Concern | Choice | Why |
|---|---|---|
| Driver | `psycopg[binary]` 3 | Current generation; clean `dict_row` factory |
| Query layer | **SQLAlchemy Core** (not ORM) | Composable query construction without session/identity-map complexity. `docs/plan.md:53` deliberately keeps `db.py` as plumbing only — Core respects that; the ORM would not. |
| Migrations | **Alembic** | Version table, ordered up/down, and — critically — data migrations, which Phase 1.2 needs |
| Pooling | SQLAlchemy `QueuePool` | Matters once >1 worker becomes viable |

Composable Core queries are the point: they give one place to enforce user
scoping in Phase 1, which raw strings scattered through `routes.py` cannot.

*Alternative considered:* raw SQL + Alembic. Simpler conceptually, but Alembic
can't autogenerate from raw SQL and the repository layer stays hand-written.
Core is the better trade here.

### 0.2 Schema translation — where the work actually is  ·  **Opus**

**Timestamps: the highest-churn item.** Every time column is ISO-8601 `TEXT` with
`DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))` — `created_at`, `published_at`,
`read_at`, `saved_at`, `last_polled_at`, `last_success_at`, `updated_at`. All
become `TIMESTAMPTZ DEFAULT now()`. Real improvement (true comparisons, index-able,
timezone-correct), but it ripples into Python: `pipeline.py:56` and every sibling
stop formatting strings and pass `datetime` objects; feedparser's parsed dates go
in directly. **Audit every string date comparison and `ORDER BY` on a date column.**

| SQLite | Postgres |
|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `GENERATED ALWAYS AS IDENTITY` |
| ISO-8601 `TEXT` dates | `TIMESTAMPTZ` |
| `INTEGER` 0/1 (`feeds.paused`) | `BOOLEAN` |
| `INSERT OR IGNORE` (`feeds.py`) | `ON CONFLICT DO NOTHING` |
| `INSERT OR REPLACE` (`pipeline.py:175`) | `ON CONFLICT (id) DO UPDATE SET …` |
| `ON CONFLICT(key) DO UPDATE` (`db.py:95`) | unchanged — already valid |
| `COLLATE NOCASE` | `UNIQUE (lower(username))` functional index |
| `PRAGMA journal_mode/foreign_keys` | gone; FKs always enforced |
| `sqlite3.Row` + `cur.lastrowid` | `dict_row` + `RETURNING id` |

`lastrowid` has no Postgres equivalent — every insert helper needs `RETURNING id`.
That includes `tests/conftest.py:51,90`.

### 0.3 FTS5 → tsvector — a genuine simplification  ·  **Sonnet**

Drop `articles_fts` and **all three triggers** (`db.py:66-79`). Replace with a
generated column:

```sql
ALTER TABLE articles ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (
    to_tsvector('english',
      coalesce(title,'') || ' ' || coalesce(summary,'') || ' ' || coalesce(full_text,''))
  ) STORED;
CREATE INDEX idx_articles_search ON articles USING GIN (search_vector);
```

No triggers to keep in sync — Postgres maintains it. `/search` (`routes.py:215`)
moves from `MATCH` to `@@ websearch_to_tsquery('english', :q)`, ordered by
`ts_rank`. `websearch_to_tsquery` handles quoted phrases and `-exclusion` the way
users expect, and won't raise on malformed input the way `MATCH` does.

**This kills a recurring hazard.** Every previous version of this plan carried a
warning that adding a searchable column means rebuilding a virtual table plus three
triggers together. Here it's one line in the generated expression. Adding
`clean_title` (Phase 3) and `topics` (Track A1) to search becomes trivial.

### 0.4 The concurrency trap Postgres *introduces*  ★ read this one  ·  **Opus**

Postgres makes `--workers 1` liftable — and that is exactly what breaks things:

- `docs/plan.md:583` §B already flagged it: **N gunicorn workers = N APScheduler
  instances**, so every job fires N times. Poll, pipeline and profile regeneration
  all duplicate.
- `pipeline.py:24`'s `_PIPELINE_LOCK` is a **`threading.Lock` — process-wide**. It
  cannot serialize across workers. Today it works only because there's one process.

Raising the worker count without addressing this gives you concurrent pipeline runs
double-summarizing articles and competing for the same Ollama GPU — the exact thing
`docs/plan.md:598` §G says to avoid.

**Two fixes, both worth doing:**
1. Replace `_PIPELINE_LOCK` with a **Postgres advisory lock**
   (`pg_try_advisory_lock(<key>)`), which serializes across processes and hosts.
   Genuinely better than the threading lock and one of the strongest arguments for
   this migration.
2. Run the scheduler as its **own container/process** (`command: python -m
   app.scheduler_main`), not inside a gunicorn worker. Cleaner separation, and the
   web tier scales freely.

**Keep `--workers 1` until both land.** Otherwise Phase 0 ships a regression that
only appears under load.

### 0.5 Data migration  ·  **Opus**

`scripts/migrate_sqlite_to_pg.py`, one-shot and re-runnable:
- stream each table SQLite → Postgres in batches, converting ISO strings to
  `datetime` and 0/1 to `bool`;
- preserve ids (Phase 1's backfill and FKs depend on them), then `setval()` every
  identity sequence to `max(id)` — **forgetting this is the classic post-migration
  bug**: the first insert collides on a duplicate key;
- verify: per-table row counts, spot-check timestamp round-trips, run a sample of
  search queries against both engines and diff results;
- 17k articles / 116 MB → a few minutes.

**The SQLite file is the rollback.** Keep it, don't delete it, and take a
`scripts/backup.py` snapshot before starting.

### 0.6 Repository layer  ·  **Opus** (interface) → **Sonnet** (extraction)

New `app/repo/` — `articles.py`, `feeds.py`, `users.py`, `settings.py`. All SQL
moves out of `routes.py` (773 lines, SQL inline throughout) into named functions.

This is not tidiness. **Phase 1.2 must add user-scoping to ~9 queries; missing one
is a cross-user data leak.** A repository gives one place where "every article
query takes a `user_id`" is enforceable and testable. Doing this *before* the
accounts work is why Phase 0 comes first.

### 0.7 Ops  ·  **Haiku**

- Postgres 16 service in `docker-compose.yml`, named volume, healthcheck,
  `depends_on: {db: {condition: service_healthy}}`.
- `DATABASE_URL` replaces `DB_PATH`. Update `.env.example`, `README.md`, `CLAUDE.md`.
- **`scripts/backup.py` rewrite** — the current one uses SQLite's `.backup` API,
  which no longer exists. Move to `pg_dump -Fc`, keeping the `BACKUP_DIR`/`KEEP`
  rotation logic.
- **Memory note:** Postgres adds ~256 MB baseline on a box already running Ollama.
  Worth a glance at headroom, since Ollama is the RAM/VRAM-hungry neighbour.

### 0.8 Tests — budget for this honestly  ·  **Sonnet**

`tests/conftest.py` is SQLite-specific throughout: `import sqlite3`,
`sqlite3.connect(":memory:")`, `executescript`, `?` placeholders, `cur.lastrowid`.
There's no in-memory Postgres, so:
- a `postgres` service for tests (docker-compose or `testcontainers`);
- each test in a transaction rolled back at teardown — faster and cleaner than
  recreating the schema per test;
- schema built by **running Alembic migrations**, which also continuously tests
  that the migrations work;
- `add_feed` / `add_article` helpers rewritten for `RETURNING id`.

Every DB-touching test changes. Against the 100% coverage target in `CLAUDE.md`,
this is a substantial slice of the phase — not an afterthought.

### 0.9 Retention, favorites, and bulk cleanup  *(requested)*

17,093 articles from **3 feeds**, with no pruning anywhere. Three requested pieces,
plus two hazards the live data exposes.

#### ⚠️ Hazard 1 — a 15-day policy would delete the entire database today

```
newest article created_at : 2026-06-12
today                     : 2026-07-25
articles older than 15d   : 17,093 of 17,093   (100%)
articles with a vote      :      26 — all older than 15 days
saved / favorited         :       0
```

The whole corpus is 43+ days old, so the **first run at 15 days removes
everything**. And because `votes.article_id` is `REFERENCES articles(id) ON DELETE
CASCADE` (`schema.sql`), it would take **all 26 votes with it** — the complete
preference-training signal, silently, via the FK.

Honoring the requested 15-day default, with guards that make it safe:
- ship the setting **enabled with the 15-day default, but inert until confirmed** —
  the first run requires an explicit confirmation in Settings;
- a **dry-run preview** showing exact counts before anything is deleted
  ("this will delete 17,093 articles, 26 votes, 0 favorites");
- the same preview available any time, so the policy's effect is never a surprise.

#### ⚠️ Hazard 2 — the preference profile is coupled to articles (must be fixed)

You called this out, and the code confirms it. The profile depends on the articles
table in **two** independent places:

```sql
-- schema.sql:44  — deleting an article destroys the vote
article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE

-- pipeline.py:147 — the profile text is read out of articles, not votes
SELECT v.value, a.title, a.summary
  FROM votes v JOIN articles a ON a.id = v.article_id
```

So the profile is not merely *at risk* from retention — it is **derived from
article rows that retention is designed to delete.** Both couplings have to go.
This is 0.9d below, and it is a **prerequisite for the first retention run**, not a
follow-up.

#### ⚠️ Hazard 3 — deleted articles come back

`feeds.py:99` dedups with `INSERT OR IGNORE INTO articles … guid`, and
`UNIQUE(feed_id, guid)` is the only thing preventing re-insertion. **That check
lives on the article row retention just deleted.**

A 15-day window against feeds that carry 30+ days of items means: prune an article
→ next poll re-inserts it as `status='new'` → it is re-scored and re-summarized
(burning Ollama calls) → it resurfaces as unread. A permanent resurrection loop,
and the deletions never stick.

**Fix — a tombstone table**, in 0.9e. Tiny rows, survives article deletion, checked
at poll time.

#### 0.9a Retention policy setting  ·  **Sonnet**

- `retention_days` setting, **default 15**, admin-only, editable in Settings.
- Scheduled daily job deleting articles older than the window.
- **Key on `created_at` (ingestion time), never `published_at`.** Concretely:
  `max(published_at)` in the live DB is `2026-10-06` — 2.5 months in the *future*,
  from a feed with bad dates. Retention keyed on publisher-supplied dates would
  keep junk forever and delete good articles early. `created_at` is ours and
  trustworthy.
- **Never delete:** favorited articles (your requirement, 0.9c) — and nothing
  outside the `articles` table at all, per the scope guarantee in 0.9e. Once 0.9d
  lands, voted articles are safely prunable because the profile no longer depends
  on them.
- `0` disables pruning entirely.
- **Batch the deletes** — 1,000 rows per statement in a loop. A single 17k-row
  `DELETE` with FK cascades and a GIN index rebuild holds a long lock.
- Post-cutover, let autovacuum reclaim the space; the 116 MB will shrink sharply.

#### 0.9b Bulk "remove read articles" *(activates fully after Phase 1)*  ·  **Sonnet**

Admin-only, in Settings: remove read articles for **a selected user**, or **all
users** via a checkbox.

**The distinction that must not be blurred:** articles are shared rows, per-user
read state is not. Deleting an article row because *user A* read it would remove it
from *user B's* list, who may never have seen it.

So the action operates on **per-user state only** — it clears the selected users'
`user_article_state` rows. Article rows are never touched directly. A separate
garbage-collection step (part of 0.9a) then deletes article rows that no user
references any more and that are past the retention window.

This makes "clean up for user A" **structurally incapable** of damaging user B's
list, rather than merely careful not to. With "all users" checked, every article
that everyone had read becomes unreferenced and the GC collects it on the next run
— the intended outcome, reached safely.

- **Confirmation:** show the count before acting ("removes 12,847 articles from 3
  users"). Destructive and irreversible — no bare submit button.
- Before Phase 1 exists there is one implicit user, so this ships as a simple
  "remove all read articles" and gains the user picker in 1.4.

#### 0.9c Favorites exempt from retention  ·  **Haiku**

**Favorites already exist** — this is mostly wiring, not a new feature.
`POST /article/<id>/save` (`routes.py:248`), the ☆/★ toggle
(`_article_card.html:27-32`), the `?saved=` filter and the "Saved" sidebar group all
ship today, recorded at `docs/improvements-next.md:56`. Currently 0 articles are
saved, which is why it may not have looked present.

What's actually needed:
1. `saved_at` moves into `user_article_state` — **already covered by Phase 1.2**, so
   favorites become per-user for free;
2. the retention job excludes any article saved by *any* user;
3. 0.9b's bulk purge skips favorites even when read — reading something you starred
   must not remove it.

Net new work: the exclusion clauses. The user-facing feature is done.

#### 0.9d Decouple the preference profile from articles  ★ prerequisite  ·  **Opus**

**The profile must stand entirely on its own.** After this, deleting every article
in the database leaves the profile and its training history fully intact.

1. **Snapshot the vote.** `votes` gains `title_snapshot` and `summary_snapshot`,
   written at vote time from the article as it was. The vote becomes a
   self-contained record of what you judged.
2. **Break the cascade.** `votes.article_id` stops being
   `NOT NULL … ON DELETE CASCADE` and becomes nullable `ON DELETE SET NULL` — kept
   as a convenience pointer to the article *while it exists*, carrying no data
   dependency. Deleting the article nulls the pointer and changes nothing else.
3. **Stop joining.** `regenerate_preferences` (`pipeline.py:147`) reads `votes`
   alone. No `JOIN articles`, no dependency on article lifetime.
4. **Backfill first.** Populate snapshots for the existing 26 votes from the
   articles that still exist — **before any retention run**, or that history is
   gone for good.

Roughly a dozen lines of production code plus one migration, and it converts the
profile from a derived view of the articles table into an independent, durable
record — which is the behaviour you described.

**One clarification this creates.** After Phase 1 there are two records of a
like/dislike, and the split is deliberate, not duplication:

| | `user_article_state.opinion` | `votes` |
|---|---|---|
| Means | what this user thinks of this article *now* | the durable training event |
| Lifetime | dies with the article | **permanent** |
| Drives | the card's like/dislike UI | the preference profile |
| Retention | prunable | **never pruned** |

#### 0.9e Scope guarantee — retention touches articles and nothing else  ·  **Sonnet**

Your requirement, stated as an invariant the implementation must satisfy:

| Table | Retention | Why |
|---|---|---|
| `articles` | **deletes** (past window, not favorited) | the intended target |
| `user_article_state` | deletes with its article | pure per-user view state |
| `search_vector` | maintained automatically | generated column |
| **`feeds`** | **never** | news sources, and `etag`/`last_modified` must survive or conditional GET breaks and every feed refetches in full |
| **`settings`** | **never** | standalone key/value; no article reference |
| **`preferences`** | **never** | the profile text; after 0.9d it has no article dependency at all |
| **`votes`** | **never** | the training record; after 0.9d it is self-contained |
| **`users`** | **never** | accounts are unrelated to article lifetime |
| `topic_rules`, `digests` | never | config and derived output (Tracks A/D) |

**Feeds are structurally safe.** The FK runs `articles.feed_id REFERENCES feeds(id)
ON DELETE CASCADE` (`schema.sql:21`) — feeds→articles, *not* articles→feeds.
Deleting every article of a feed cannot delete the feed. A feed pruned to zero
articles keeps its title, tags, threshold override, pause state, health counters
and conditional-GET tokens, and simply refills on the next poll.

**Tombstones (fixes Hazard 3):**

```sql
CREATE TABLE seen_guids (
    feed_id    INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    guid       TEXT    NOT NULL,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (feed_id, guid)
);
```

Written on first ingest, **never deleted by retention**, and checked at poll time
alongside the existing `ON CONFLICT DO NOTHING`. A pruned article stays pruned even
while it is still in the feed XML. Rows are two small columns — tens of thousands
cost almost nothing next to the 116 MB of article text they let you reclaim.

*(Cascade-deleting tombstones when their **feed** is deleted is correct: removing a
source should let a re-added feed start clean.)*

**Test the invariant directly:** seed one row in every table, run retention with a
window of 0 days, and assert that `articles` shrank and **every other table's row
count is unchanged**. That single test encodes the whole guarantee and will catch
any future join or cascade that quietly widens the blast radius.

**Effort:** M for the section (0.9d is S). **Risk:** medium — the only part of this
plan that deletes user data. The dry-run preview, the per-user/global split, the
0.9d decoupling and the tombstones are what bring it down.

**Phase 0 total: L+ — realistically 1.5–2 weeks.** The long poles are the timestamp
conversion, the test-suite port, and the repository extraction.

---

## Phase 1 — Accounts, roles, and per-user state  *(requested)*  ·  **Opus**-led

Four sequential steps; each independently testable.

### 1.1 Users, sessions, registration  ·  **Opus**

```sql
CREATE TABLE users (
    id                   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username             TEXT        NOT NULL,
    password_hash        TEXT        NOT NULL,
    role                 TEXT        NOT NULL DEFAULT 'user'
                                     CHECK (role IN ('user','admin')),
    must_change_password BOOLEAN     NOT NULL DEFAULT false,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at        TIMESTAMPTZ
);
CREATE UNIQUE INDEX idx_users_username ON users (lower(username));
```

- `GET|POST /register` — open. **First account created is `admin`**, all later ones
  `user`. Decide via `SELECT COUNT(*) FROM users` **inside the insert's
  transaction**; with Postgres, take it `FOR UPDATE` or rely on a serializable
  transaction so two simultaneous first registrations can't both become admin.
  (Under SQLite's single writer this was free; under Postgres it is not.)
- `GET|POST /login`, `POST /logout`.
- `werkzeug.security.generate_password_hash` (scrypt) / `check_password_hash`.
  Never a bare hash, never a hand-rolled comparison.
- Minimum password length 10, enforced server-side.
- Login throttling: per-username backoff after 5 failures. With multiple workers
  this belongs in Postgres, not process memory — a small `login_attempts` table.
- `before_request` requiring a session for everything except `/login`, `/register`,
  `/static/*`, `/static/manifest.json`, `/static/sw.js` — the last two must stay
  open or the PWA stops installing.
- **HTMX-aware redirects.** A fragment request on an expired session must not swap
  a login page into `#article-list`. When `HX-Request` is present, return `401`
  with `HX-Redirect: /login` rather than a 302. Most likely thing to get wrong.

**Also:** bind `docker-compose.yml` to `"127.0.0.1:5001:5000"` — what
`docs/plan.md:486` specified and what the inline comment still claims. Tailscale
reaches localhost-bound ports.

**Effort:** M. **Risk:** low.

### 1.2 Split pipeline status from user opinion  ★ load-bearing migration  ·  **Opus**

Must land **before** a second account exists.

```sql
CREATE TABLE user_article_state (
    user_id      INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    article_id   INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    read_at      TIMESTAMPTZ,
    saved_at     TIMESTAMPTZ,
    dismissed_at TIMESTAMPTZ,
    opinion      TEXT CHECK (opinion IN ('liked','disliked')),
    PRIMARY KEY (user_id, article_id)
);
CREATE INDEX idx_uas_user ON user_article_state (user_id);
```

- `articles.status` narrows to the lifecycle only: `new → scored → hidden | summarized`.
- `votes` gains `user_id` (NOT NULL, FK).
- `articles.read_at` / `saved_at` **can now actually be dropped** — Postgres does
  `DROP COLUMN` cheaply, and Alembic can express it with a working downgrade. Under
  SQLite this needed a table rebuild and the plan deferred it. A concrete dividend
  of Phase 0.

**Backfill** — a proper Alembic data migration, which is precisely what the old
`ALTER TABLE`-list mechanism could not do:
- `status IN ('liked','disliked')` → `user_article_state` row for the admin with
  matching `opinion`; `status = 'summarized'`;
- `status = 'dismissed'` → `dismissed_at` set; `status = 'summarized'`;
- existing `read_at` / `saved_at` copied across before the columns drop;
- all existing `votes` rows get the admin's `user_id`.

**Query changes — the repository layer from 0.6 is what makes this safe.** Every
article read gains `LEFT JOIN user_article_state s ON s.article_id = a.id AND
s.user_id = :uid` filtering `s.dismissed_at IS NULL`: `/articles` (161), `/search`
(215), `/count` (698), `/article/<id>/save` (249), `/article/<id>/dismiss` (275),
`/vote` (291), `/article/<id>/content` (670), `/dismiss-all` (728),
`/sidebar/feeds` (319 — unread counts become per-user).

**Shared preference profile:** `preferences` keeps its single-row constraint.
Everyone's votes feed one profile — that's what "shared ranking" means.
`regenerate_preferences` (`pipeline.py:142`) is unchanged unless you later weight
by user, which `votes.user_id` now permits.

**Tests:** two users' dismissals independent; A's like doesn't mark read for B;
per-user unread counts; backfill idempotent; `dismiss-all` scopes to caller.

**Effort:** L. **Risk:** medium — down from medium-high, because Alembic makes it
reversible and the repository centralises the scoping.

### 1.3 Roles and route gating  ·  **Sonnet**

`@login_required` and `@admin_required` in `app/auth.py`.

| Area | Routes | Access |
|---|---|---|
| Reading | `/`, `/articles`, `/search`, `/count`, `/status`, `/article/<id>/content` | any user |
| Reacting | `/vote/…`, `/article/<id>/save`, `/article/<id>/dismiss`, `/dismiss-all` | any user |
| Own account | `/profile`, `/profile/password` | any user |
| Settings | `/settings`, `/settings/{models,embeds,ollama,titles,content}` | **admin** |
| Feeds | `/manage-feeds`, `POST\|DELETE /feeds…`, `/feeds/opml`, `/feeds/<id>/{pause,resume,threshold,tags}` | **admin** |
| Pipeline | `/poll`, `/rescore-hidden`, `/preferences/regenerate` | **admin** |
| Shared profile | `GET /preferences` / `POST /preferences` | any user (read-only) / **admin** |

The shared profile stays readable by all — it explains why articles rank as they
do, and hiding it makes ranking inscrutable — but only admins rewrite it, since it
affects everyone.

Hide what a role can't reach (gear icon, Manage Feeds pencil in
`_sidebar_feeds.html` / `base.html`). **Gating the UI is not gating the route — do
both.** Test every admin route returns 403 for a plain user.

**Effort:** M. **Risk:** low.

### 1.4 Profile pages and admin user management  ·  **Sonnet** (templates **Haiku**)

**`/profile` — both roles:** username, role badge, member since, last login;
change-own-password (current required, new twice); personal stats from
`user_article_state` + `votes` — read count, votes cast, like rate, saved count.

**`/admin/users` — admin only:**
- user table: username, role, created, last login;
- **reset a user's password** — admin sets or generates a temporary one shown
  **once**; row gets `must_change_password = true`. Admins never see existing
  passwords; only hashes are stored, so "reset" means overwrite;
- promote/demote `user` ↔ `admin`;
- delete (cascades `user_article_state` and `votes` via FK);
- **guard: the last admin cannot be demoted or deleted.** Enforce in logic. With
  concurrent workers, do it in a transaction with the row locked — two simultaneous
  demotions could otherwise leave zero admins.

**Forced password change:** while `must_change_password`, `before_request`
redirects everything except `/profile/password` and `/logout`.

**Bulk cleanup gains its user picker here.** 0.9b ships in Phase 0 as a single
"remove all read articles" action (one implicit user); once `users` exists it grows
the per-user selector and the "all users" checkbox described there.

**CSRF:** destructive admin actions get a per-session token in a hidden field,
validated on POST. `SameSite=Lax` blocks cross-site form POSTs in current browsers,
but this is where ~20 lines of defence in depth earns its keep.

**Effort:** M. **Risk:** low.

**Phase 1 total: L+ — 1.5–2 weeks**, much of it 1.2 plus authenticating every
fixture in `tests/test_routes.py`.

---

## Phase 2 — Ollama host and port in Settings  *(requested)*  ·  **Sonnet**

**The obstacle:** `ollama_client.py` reads `OLLAMA_BASE = os.environ.get("OLLAMA_HOST", …)`
**at import time**, as a module constant. Runtime config means it can't stay one.

**Shape** — mirror the model-selection pattern (`_scoring_model(db)`,
`pipeline.py:27`, reading `get_setting(db, "scoring_model", DEFAULT)`):

- Settings rows `ollama_host` and `ollama_port`, composed into `http://{host}:{port}`.
  Env vars stay the fallback, so an untouched install behaves as today.
- `generate()` and `list_models()` gain `base_url: str | None = None`, defaulting to
  the env constant. Callers holding a connection resolve the setting and pass it —
  keeping `ollama_client` free of app state, which `docs/plan.md:53` calls out as
  deliberate ("No knowledge of app state").
- Admin-only form on `settings.html`: host, port, Save.
- **"Test connection" button** — calls `list_models()` against the *entered* values
  before saving, reporting reachable / model count / error string. Without it you
  save a typo'd IP and every score fails silently for 30 minutes until you read the
  logs. This is what makes the feature usable, not a nicety.
- Validation: non-empty host, integer port 1–65535, sane hostname/IP shape.
  Admin-only and self-hosted, so input hygiene rather than an SSRF boundary.

**Tests:** setting overrides env; unset falls back to env; test-connection surfaces
success and failure without raising; port validation rejects `0`, `70000`, non-numeric.

**Effort:** S–M. **Risk:** low. The scheduler picks up new values on its next job
because the setting is read per run — no restart needed; say so in the UI.

---

## Phase 3 — De-clickbait titles  *(requested)*  ·  **Sonnet**

**Setting:** `declickbait_enabled`, default **off**, admin-only. Affects everyone,
since articles are shared.

**Fold it into the existing summarization call, not a new one.**
`summarize_scored_articles` (`pipeline.py:106`) already holds the full text. With
the setting on, switch that call to `expect_json=True` and request both fields:

```json
{"summary": "…", "clean_title": "…", "was_clickbait": true}
```

**Zero extra Ollama calls.** A separate rewrite pass would add one call per article
to the slowest pipeline stage for no benefit. Setting off → existing plain-text path
untouched.

**Storage:** `articles.clean_title TEXT`, `articles.title_was_clickbait BOOLEAN`.

**Never overwrite `articles.title`.** The original feeds the search vector, the
duplicate fingerprints (Track A2), and your ability to see what the model changed.
Rewriting in place makes the edit invisible and irreversible.

**Prompt** (`prompts.declickbait_*`, following the XML-delimiter injection
convention from `docs/plan.md:244`):
- resolve withheld information rather than deleting it — *"You won't believe what
  the CEO said"* → *"CEO says X"*. A title that omits the payoff **is** the problem;
- preserve every proper noun, number and factual claim; invent nothing;
- no editorialising, no added adjectives; ≤ 90 characters;
- return `was_clickbait: false` and echo the original when the title is already
  plain. Most are — rewriting all of them is how this becomes annoying.

**Display:** show `clean_title` only when the setting is on *and* `was_clickbait`,
with the original beneath in small muted text (reuse the `score_reason` styling) so
the change stays checkable. Fall back to the original whenever `clean_title IS
NULL` — covers every article summarized before the feature was enabled.

**Search:** add `clean_title` to the generated `search_vector` expression (0.3) —
one line, no trigger rebuild.

**Tests:** JSON populates both fields; malformed JSON falls back to plain-text
summarization and leaves `clean_title` NULL **rather than losing the summary**;
`was_clickbait: false` leaves the title alone; cards render for pre-feature articles.

**Effort:** M. **Risk:** medium — two JSON fields from a 3b model is measurably less
reliable than free text. The fallback is the safety net: **a parse failure must
still produce a summary.** Test that specifically. Escape hatch if flaky: a separate
call behind the same setting.

---

## Phase 4 — Strip or frame irrelevant article sections  *(requested)*  ·  **Sonnet**

**The problem:** publishers pad articles with "related stories", recaps of older
coverage and newsletter CTAs to keep you scrolling. In the reader they read as part
of the article and waste time.

**Setting:** `content_filter_mode`, admin-only — `off` (default) · `highlight` ·
`remove`.

### Detection: two passes, cheap one first

**Pass 1 — deterministic, no LLM.** Catches the formulaic cases: lines beginning
`Related:` / `Read more:` / `See also:` / `More coverage:` / `Previously:`; runs of
consecutive link-only lines; `Sign up for our newsletter…`; `This article was
originally published…`; trailing blocks that are a bare headline plus a date. There
is precedent — `_clean_content` (`routes.py:68`) already strips a leading body line
duplicating the title or description.

**Pass 2 — LLM, behind its own `content_filter_llm` setting.** The "older news
recap" case is semantic, not formulaic: a paragraph summarising last month's
developments looks exactly like a paragraph of the article. Number the paragraphs,
ask which are tangential, get indices back:

```json
{"asides": [{"index": 7, "kind": "older_news"}, {"index": 9, "kind": "related_links"}]}
```

**A separate Ollama call, not another field on the summarization response.** Phase 3
already pushes that call to two fields; adding a structured array would make a 3b
model's JSON materially less reliable, and a failure there costs you the summary.
This pass also needs different input (paragraph-numbered text). Cost: +1 call per
summarized article, only when enabled — which is why it's a separate switch from the
display mode.

### Storage

`articles.aside_spans JSONB` — character offsets into `full_text`:

```json
[{"start": 2411, "end": 2680, "kind": "older_news", "label": "Older coverage"}]
```

Offsets, not block indices: `full_text` is immutable once stored, whereas
`_to_blocks` (`routes.py:96`) is render-time logic that may change. Store the
`full_text` length alongside and discard spans that no longer match. `JSONB` (rather
than the `TEXT` this would have been under SQLite) means you can query and index
these later — e.g. "how often is pass 2 firing?" for Track B2.

Classification runs **once at summarize time** and is stored — never recomputed per
render.

### Rendering

`_to_blocks` gains span awareness: blocks overlapping a span are tagged `aside:
true` with their `kind`, and `_article_content.html` branches on the mode:

- **`highlight`** — framed, muted container with a small label ("Older coverage",
  "Related links"), collapsed to one line, click to expand. The mode you described,
  and the right default once enabled.
- **`remove`** — omit the block, but show a `2 sections hidden — show` affordance
  where it was.

**Even `remove` should be recoverable.** Silently deleting text is the one way this
feature can actively mislead you — a bad classification would erase real content
with no trace. The show-link costs one line of template and removes that failure
mode entirely.

**Tests:** each deterministic pattern in isolation; spans from both passes merge
rather than double-count; malformed LLM JSON yields no spans and the article renders
in full (**never** a blank reader); `off` ignores stored spans; `remove`'s show-link
restores text; spans stale against changed `full_text` are discarded.

**Effort:** M–L. **Risk:** medium — false positives hide real content. Three things
keep it safe: default off, `highlight` before `remove`, recoverability in both. Ship
pass 1 alone first and see how far formulaic detection gets before paying for pass 2.

---

## Track A — Make the ranking directable *(proposed)*  ·  **Sonnet** (A4 **Haiku**)

`docs/plan.md`'s success criterion was *"after ~2 weeks of voting, top-10 feels
accurate ≥70% of the time"*. Nothing measures it, and the only steering is a binary
vote feeding free-text prose. **Note: 26 votes so far** — the profile is running on
very little signal, which makes A1 and A3 more valuable than they'd otherwise be.

**A1 · Topic tagging + deterministic mute/boost ★ highest leverage.** Extend
`prompts.scoring_prompt` to also return `topics: ["slug", …]` — **same call, no
extra cost**. Store on `articles.topics` (a Postgres `TEXT[]`, properly indexable
with GIN, rather than the comma-joined string SQLite forced). Add `topic_rules`
(`topic`, `adjustment REAL`, `muted BOOLEAN`). Apply after the clamp at
`pipeline.py:87`: `score = clamp(score + Σ adjustments)`; muted → `status='hidden'`
with `score_reason` prefixed `Muted topic: …`. Topic chips on cards (click to
filter), admin-only rules panel. Gives hard, auditable control over a soft LLM score
instead of hand-editing prose and hoping a 3b model honours it. **M / medium** —
pass the 20 most-frequent topics in as a vocabulary and normalise slugs server-side.

**A2 · Cross-feed duplicate clustering.** HN + The Verge + Ars carry the same story;
all score high; the top-10 becomes one story three times. **No LLM.** New
`app/dedupe.py`: canonical URL (strip `utm_*`/`fbclid`/`ref`, lowercase host, drop
`www.` and trailing slash) plus a title fingerprint (lowercase, drop stopwords, hash
the sorted token set; ≥70% overlap clusters). `articles.cluster_id`, assigned at
insert. `/articles` groups by cluster, showing the top-scoring member with "Also in:
…" chips. Fingerprint the **original** title, not the de-clickbaited one.
*Postgres bonus:* `pg_trgm` similarity makes fuzzy title matching a built-in index
operation rather than hand-rolled shingling — worth using instead. **M / low** —
bias conservative; keep every member reachable.

**A3 · Ranking insights dashboard (`/insights`, admin).** Pure SQL over `votes` +
`user_article_state`: score histogram with the threshold drawn in; **agreement
rate** (% of likes scoring above threshold, % of dislikes below); per-feed like-rate
surfacing "feeds you never like"; per-topic rates once A1 lands; **suggested
threshold** from sweeping 0.0→1.0 in 0.05 steps to maximise agreement. Postgres
window functions and `width_bucket()` make the histogram and sweep one query each.
Inline SVG charts — no charting library. **M / low.**

**A4 · One-click threshold tuning.** "Apply suggested threshold" writing the global
value, plus per-feed suggestions writing `feeds.score_threshold` (column exists).
Pairs with `POST /rescore-hidden` (`routes.py:750`) to retroactively surface what
the new threshold would have kept. **S / low.**

---

## Track B — Speed and trust *(proposed)*  ·  **Sonnet** (B2 **Haiku**)

**B1 · Batched scoring.** `score_new_articles` makes one serial call per article, up
to 50 per run — 2–3 minutes before summarization starts. Batch 8 per prompt
returning a JSON array keyed by article id (`SCORING_BATCH_SIZE`, default 8; `1`
reproduces today exactly). On parse failure or id mismatch, **fall back to
per-article scoring for that batch** — never drop articles. ≈−80% call count.
**M / medium**; the fallback is the safety net, so test it hard. Must not introduce
*parallel* calls — `docs/plan.md:598` §G: concurrent requests contend for GPU VRAM.

**B2 · Pipeline observability.** `pipeline_runs` table (`started_at`, `finished_at`,
`scored_n`, `summarized_n`, `llm_ms_total`, `errors_n`, `skipped`) written by
`run_pipeline`; last 20 runs on `/insights`. Turns `LOG_FORMAT=json` into something
visible, and becomes more valuable once 0.4's scheduler split means jobs run outside
the web process. **S / low.**

**B3 · High-score notifications** *(the one unfinished roadmap item)*. The index
already polls `/status` every 3s after a refresh. Extend that JSON with
`high_score_ids` (summarized, unread **for the calling user**, `score >=
HIGH_SCORE_NOTIFY`, default 0.8, not yet notified); fire a `Notification` per id,
opt-in per user; track notified state in `user_article_state` so it fires once per
person. `navigator.setAppBadge` is already wired. **S / low** — iOS Safari only
allows notifications for installed PWAs; document rather than fight it.

---

## Track C — Ingestion reach *(proposed)*  ·  **Sonnet** (C2 **Haiku**)

**C1 · Extraction fallback chain.** `fetch_full_text_and_image` (`pipeline.py:256`)
is one `httpx.get` → trafilatura → `feed_content` → `raw_snippet`. When a site
blocks the `rss-reader/1.0` UA, both the summary *and the score* are built from a
200-char blurb — a silent quality tax. Add rungs: browser-like UA + `Referer`; then
`readability-lxml` when trafilatura yields < 200 chars. Record the winning rung in
`articles.extract_source`. Keep any third-party reader proxy or archive service
**opt-in and off by default** — it would send your reading list off-box, against the
point of local hosting. **M / low.**

**C2 · Per-feed extraction health.** `% of articles with real full text` and the
dominant `extract_source` per feed in `/manage-feeds`, beside the existing failure
badges. Makes a quietly useless feed visible. **S / low.**

**C3 · YouTube channel feeds with transcripts.**
`youtube.com/feeds/videos.xml?channel_id=…` ingests today, but with no body both
scoring and summarization run on a description line. Detect YouTube URLs, pull
captions via `youtube-transcript-api`, summarize with a transcript-specific prompt
(spoken text summarizes badly under the article prompt). **M / medium**, stated
plainly: the transcript API is unofficial, rate-limited and breaks periodically.
Best-effort, clean fallback to the description, never blocks summarization.

**C4 · Newsletter ingest via IMAP.** Much good writing is newsletter-only. IMAP
polling beats inbound mail: no MX records, no SMTP server, any existing mailbox. File
newsletters into a folder with a provider-side filter; a scheduler job polls via
`imaplib` and creates articles under a synthetic feed per sender (`feeds.url` =
`mailto:sender@domain`), HTML part through the C1 chain. Credentials in env, never
the DB. Mock IMAP entirely, per the existing "no live services" rule. **L / medium**
— schedule last.

---

## Track D — Reading experience *(proposed)*  ·  **Sonnet** (D3 **Haiku**)

**D1 · Daily digest.** Cron at 07:00 (beside `regen_prefs` at 02:00,
`scheduler.py:40`) turning the top ~10 unread summarized articles of the last 24h
into one ~150-word themed brief, each claim linked to its source. `digests` table,
`prompts.digest_prompt`, `GET /digest`, dismissible card atop the index. With shared
ranking, one digest serves everyone. **M / low.**

**D2 · True offline reading.** `static/sw.js` is 39 lines and network-first for
`/articles`; offline on a phone currently gets you very little, undercutting the
Tailscale-on-mobile use case. Cache `/article/<id>/content` as opened; "Download top
20 for offline"; cache-first with background revalidation; offline banner; votes
queued in IndexedDB and flushed on reconnect. **M / medium** — the vote queue is
fiddly and can ship second; cached reading alone is most of the value.

**D3 · Markdown / Obsidian export.** `GET /export/markdown?scope=saved|liked|all`
streaming a zip of one `.md` per article with YAML front matter (title, clean title,
url, feed, published, score, topics, summary) and the body, scoped to the calling
user. **S / low.**

---

## Summary — task list with model assignment

### Model key

Extends the convention already used in `docs/plan.md` ("Task List & Recommended
Models"), which assigned **Haiku** to mechanical/config work and **Sonnet** to
logic/orchestration, and noted Opus wasn't needed for the original MVP. This plan
*does* reach Opus territory, because it contains irreversible data migrations,
a security boundary, and cross-process concurrency — none of which the MVP had.

| Model | Use for | Signature |
|---|---|---|
| **Haiku** | Mechanical, fully-specified, single-concern: config, docker/env, templates, CSS, boilerplate CRUD forms, additive columns | A wrong answer is obvious immediately |
| **Sonnet** | Logic and orchestration: multi-file features, prompt design, query rewrites, algorithms, test suites | A wrong answer shows up in tests |
| **Opus** | Architecture and irreversible correctness: data migrations that destroy the source, security boundaries, cross-process concurrency, schema decisions everything else depends on | **A wrong answer is silent, and you find out weeks later** |

The Opus items share one property: **failure is not loud.** A botched timestamp
conversion, a missed user-scoping clause, a cascade that eats your votes, or a
lock that doesn't hold across processes all produce a system that looks fine.

### Task list

| # | Task | Effort | Risk | **Model** | Why this model |
|---|---|---|---|---|---|
| **−1** | Restore service (resume feeds, start Ollama) | S | — | **Haiku** | Ops actions, no code |
| **−1.1** | Auto-paused feeds auto-recover | S | Low | **Sonnet** | Scheduler job + backoff logic |
| **−1.2** | Health check reflects ingestion | S | Low | **Haiku** | Compose + one query |
| **0.1** | SQLAlchemy Core + Alembic scaffolding | S | Low | **Sonnet** | Standard wiring, well-trodden |
| **0.2** | Schema translation (TIMESTAMPTZ, types, `lastrowid`) | L | **High** | **Opus** | Ripples through every date comparison; errors are silent |
| **0.3** | FTS5 → tsvector generated column | M | Low | **Sonnet** | Contained, and the spec is settled |
| **0.4** | Advisory lock + scheduler process split | M | **High** | **Opus** | Cross-process concurrency; only fails under load |
| **0.5** | SQLite→Postgres data migration script | M | **High** | **Opus** | Irreversible; sequence resets; verification design |
| **0.6a** | Repository layer — interface design | S | Med | **Opus** | Every later user-scoping guarantee rests on this shape |
| **0.6b** | Repository layer — mechanical extraction | L | Low | **Sonnet** | Volume work once the interface exists |
| **0.7** | docker-compose, `pg_dump` backup, env vars | S | Low | **Haiku** | Pure config |
| **0.8** | Test-suite port to Postgres fixtures | L | Med | **Sonnet** | Large, fiddly, but verifiable |
| **0.9a** | Retention policy (15-day default) | S–M | **Med** | **Sonnet** | Deletion logic with explicit guards |
| **0.9b** | Bulk remove-read, per user / all users | M | **Med** | **Sonnet** | Per-user vs global semantics already specified |
| **0.9c** | Favorites exempt from retention | S | Low | **Haiku** | Exclusion clauses; feature already exists |
| **0.9d** | Decouple preference profile from articles | S | Low | **Opus** | Small code, **one-shot backfill** — get it wrong and vote history is gone |
| **0.9e** | Scope guarantee + guid tombstones | S–M | Low | **Sonnet** | Schema + the invariant test |
| **1.1** | Users, sessions, open registration | M | Low | **Opus** | Security boundary; first-admin race; HTMX 401 handling |
| **1.2** | Split pipeline status / user opinion | L | Med | **Opus** | Load-bearing migration; a missed clause leaks across users |
| **1.3** | Roles + route gating | M | Low | **Sonnet** | Mechanical once the matrix is fixed |
| **1.4** | Profile pages + admin user management | M | Low | **Sonnet** | CRUD + guards (templates: Haiku) |
| **2** | Ollama host/port + test-connection | S–M | Low | **Sonnet** | Import-time refactor + validation (form/CSS: Haiku) |
| **3** | De-clickbait titles | M | Med | **Sonnet** | Prompt design + JSON fallback path |
| **4** | Strip / frame irrelevant sections | M–L | Med | **Sonnet** | Detection + rendering (span storage design: Opus) |
| A1 | Topic tagging + mute/boost | M | Med | **Sonnet** | Prompt extension + score adjustment |
| A2 | Cross-feed duplicate clustering | M | Low | **Sonnet** | Self-contained algorithm |
| A3 | Ranking insights dashboard | M | Low | **Sonnet** | Analytical SQL + inline SVG |
| A4 | One-click threshold tuning | S | Low | **Haiku** | Two forms over an existing column |
| B1 | Batched scoring | M | Med | **Sonnet** | Batching + fallback correctness |
| B2 | Pipeline observability | S | Low | **Haiku** | One table, one insert, one view |
| B3 | High-score notifications | S | Low | **Sonnet** | Once-only semantics + client JS |
| C1 | Extraction fallback chain | M | Low | **Sonnet** | Ordered strategy chain |
| C2 | Per-feed extraction health | S | Low | **Haiku** | Aggregate query + badges |
| C3 | YouTube transcripts | M | Med | **Sonnet** | Third-party API with fallback |
| C4 | Newsletter IMAP ingest | L | Med | **Sonnet** | Largest feature, but well-specified |
| D1 | Daily digest | M | Low | **Sonnet** | Prompt + scheduled job |
| D2 | True offline reading | M | Med | **Sonnet** | Service worker + IndexedDB queue |
| D3 | Markdown export | S | Low | **Haiku** | Serialize + zip |

Bold `#` = your explicit requests.

**Distribution:** Opus ×7 (all in Phases 0–1), Sonnet ×22, Haiku ×8.

**Read the Opus set as a risk register.** They are 0.2, 0.4, 0.5, 0.6a, 0.9d, 1.1
and 1.2 — every one of them in the Postgres migration or the accounts work, and
every one capable of failing quietly. If you only supervise a handful of tasks
closely, supervise those. Everything from Phase 2 onward is Sonnet or Haiku, which
is a fair signal that the feature work is genuinely lower-stakes than the
foundational work underneath it.

**Sequencing.** `0 → 1.1 → 1.2 → 1.3 → 1.4` is a hard chain: Postgres before
accounts (or you migrate twice), and the repository layer (0.6) before the
user-scoping rewrite (1.2). **Phases 2, 3 and 4 are independent of everything** —
any can be built first. **Phase 2 is the smallest and makes the best warm-up**, and
shipping it before Phase 0 gives you something working while the migration looms.

**Front-load the risk.** Phases 0 and 1 are ~3–4 weeks combined and touch
everything. Phases 2–4 are ~2 weeks combined and touch little. If you want visible
progress early, do 2 → 3 → 0 → 1 → 4.

**Settings page:** five new admin toggles land across Phases 2–4 (`ollama_host`,
`ollama_port`, `declickbait_enabled`, `content_filter_mode`, `content_filter_llm`).
Reorganise `settings.html` into labelled sections during Phase 2 rather than
appending forms indefinitely.

---

## Cross-cutting notes

**Migrations are now Alembic.** `db.py:33-46`'s `ALTER TABLE` list and its
`except Exception: pass` are deleted in Phase 0. Every schema change after that is a
versioned, ordered, reversible migration — which is what makes 1.2's backfill and
the `read_at`/`saved_at` drop possible at all.

- New columns: `articles.clean_title`, `title_was_clickbait`, `aside_spans` (JSONB),
  `topics` (`TEXT[]`), `cluster_id`, `extract_source`, `search_vector` (generated);
  `votes.user_id`, `votes.title_snapshot`, `votes.summary_snapshot` (0.9 — decouples
  the preference profile from article retention).
- New tables: `users`, `user_article_state`, `seen_guids` (0.9e tombstones),
  `topic_rules`, `pipeline_runs`, `digests`, `login_attempts`.
- Changed constraint: `votes.article_id` → nullable `ON DELETE SET NULL` (0.9d).
- Dropped: `articles_fts` + its three triggers; `articles.read_at`, `saved_at`.
- New settings rows: `ollama_host`, `ollama_port`, `declickbait_enabled`,
  `content_filter_mode`, `content_filter_llm`, `retention_days`.

**Back up before 0.5, 0.9 and 1.2.** All three rewrite or delete data in place —
0.9's first retention run is the only one that is genuinely irreversible. Note that
`scripts/backup.py` itself changes to `pg_dump` in 0.7 — don't reach for the old one
after the cutover.

**Only one part of this plan deletes user data: 0.9.** Everything else adds,
transforms or renders. Treat its confirmation flow and dry-run preview as
requirements, not polish.

**Search is now one line, not a trigger trio.** Adding `clean_title` (Phase 3) or
`topics` (A1) to the generated `search_vector` expression is a single migration.
The standing warning about rebuilding a virtual table plus three triggers together
no longer applies — that hazard is gone.

**Three features write to the summarize path** (`clean_title`, `aside_spans`,
`extract_source`). Keep each failure independent: **any of them failing must still
leave a stored summary.** The most likely place for a cascading regression.

**Ollama stays serialized.** `docs/plan.md:598` §G and `CLAUDE.md` both record that
concurrent calls contend for GPU VRAM. B1 cuts the *number* of calls; it must not
make them parallel. And per 0.4, the advisory lock — not the old `threading.Lock` —
is what enforces this once there's more than one process.

**Coverage.** `CLAUDE.md` states 100%, one test module per `app/` module. New modules
(`auth.py`, `content_filter.py`, `dedupe.py`, `insights.py`, `email_ingest.py`, the
`repo/` package) each need theirs. Phases 0 and 1 additionally require porting the
whole suite to Postgres fixtures and then authenticating them — budget for it as
real work, not cleanup.

**No build step.** The HTMX + inline-SVG, zero-CDN stance holds throughout,
including the `/insights` charts. `docs/improvements-next.md`'s "don't split the
frontend yet" verdict still stands — nothing here revisits it.

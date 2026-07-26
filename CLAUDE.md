# Better Read — Codebase Guide

## What this is
Single-user, self-hosted RSS reader with LLM-powered relevance ranking.
Flask app in Docker; Ollama on Windows host; **Postgres 16** in the `db` compose service.

## Key files
- `app/__init__.py` — Flask app factory (`create_app`). Start here.
- `app/db.py` — SQLAlchemy engine + `get_setting`/`set_setting`. `get_db()` inside a request (auto-commits on a clean response, rolls back on error); `get_db_direct()` outside.
- `app/models.py` — schema as SQLAlchemy Core metadata. The single source of truth for columns and types.
- `app/repo/` — **all article SQL**. Every function takes `user_id`: article rows are shared, read state is not.
- `app/pipeline.py` — LLM scoring + summarization. Pipeline runs are serialized via a process-wide `_PIPELINE_LOCK`.
- `app/ollama_client.py` — All Ollama HTTP calls. `generate()` (with retries) and `list_models()`.
- `app/prompts.py` — The LLM prompts. Edit here to tune behavior.
- `app/llm_config.py` — **the registry of every Ollama job** and which model runs it. Adding a `generate()` call means adding an Action here; `tests/test_llm_config.py` fails if a prompt builder is not registered.
- `app/content_filter.py` — Detects article padding (related rails, promos, older-news recaps). Pass 1 is regex at render time; pass 2 is an optional LLM call stored as fingerprints.
- `app/routes.py` — Flask routes. HTMX-first: most return HTML fragments.
- `app/auth.py` — accounts, sessions, `@login_required` / `@admin_required`.
- `app/feeds.py` — feedparser polling. `poll_all_feeds(app)` is the entry point.
- `app/scheduler.py` — APScheduler wiring. Jobs registered here.
- `app/digest.py` — the "what you missed" briefing. Per-user (unread is per-user), cached against a fingerprint of the unread set so it only regenerates when that set changes.
- `app/extract.py` — ordered extraction chain; the winning rung is stored on `articles.extract_source`.
- `app/export.py` — Markdown/zip export, scoped to the calling user.
- `app/topics.py` — topic slugs + the mute/boost rules layered over the LLM score.
- `app/insights.py` — ranking-accuracy queries behind `/insights`.
- `app/health.py` — feed auto-recovery + the ingestion-aware `/health`.
- `app/worker.py` — the scheduler **process** (`python -m app.worker`). APScheduler is in-process, so hosting it in gunicorn means one scheduler per worker and every job firing N times. `RUN_SCHEDULER_IN_WEB=1` opts back into the old behaviour.
- `app/retention.py` — pruning + bulk clear-read. **Touches `articles` and per-user state only** (see the scope test in `tests/test_retention.py`).

## Running locally
```
docker compose up --build          # db + web + worker
docker compose exec web alembic upgrade head    # migrations run on boot too
```
Requires: Ollama running on host with `OLLAMA_HOST=0.0.0.0:11434` (env var set before starting Ollama).

## Environment variables
See `.env.example`. Copy to `.env` before first run. Required vars:
- `OLLAMA_HOST` — default `http://host.docker.internal:11434`. Overridable at runtime via Settings → Ollama → Connection (`settings.ollama_host` + `settings.ollama_port`); the env var is the fallback when either is blank.
- `OLLAMA_TIMEOUT` — seconds per Ollama call, default `180`. Bump for 8b+ models on remote/slower hardware.
- `SCORING_MODEL` — default `llama3.2:3b`. Overridable at runtime via Settings (`settings.scoring_model`).
- `SUMMARY_MODEL` — default `llama3.2:3b`. Overridable at runtime via Settings (`settings.summary_model`).
- `SCORE_THRESHOLD` — float 0-1, default `0.35`
- `SCORING_SNIPPET_CHARS` — chars of article text fed to scorer, default `2000`
- `FLASK_SECRET_KEY` — set to a random string
- `LOG_FORMAT` — `json` switches root logger to single-line JSON; default is human-readable.
- `DB_PATH` / `BACKUP_DIR` / `KEEP` — read by `scripts/backup.py` for the SQLite backup helper.

## DB schema
See `app/models.py`. `init_db()` creates missing tables on startup.

**`articles.status` is the pipeline lifecycle only** — `new → scored → hidden | summarized`. What a *person* thinks of an article (liked/disliked/dismissed/read/saved) lives in `user_article_state`, keyed by `(user_id, article_id)`. Conflating them is how one user's dismiss removes an article from everyone's list.

`votes` is the durable training record: user-scoped, carrying `title_snapshot`/`summary_snapshot`, with `article_id` nullable `ON DELETE SET NULL`. `regenerate_preferences` reads the snapshots and never joins `articles`, so retention can prune freely without touching the preference profile.

`seen_guids` tombstones every ingested `(feed_id, guid)` so a retention-deleted article is not re-ingested by the next poll — the `UNIQUE(feed_id, guid)` constraint can't do that job, it lives on the row that was deleted.

Search is a generated `tsvector` column with a GIN index (no triggers). Adding a field to the index is one line in `app/models.py`.

Tables: `feeds`, `articles`, `votes`, `preferences` (single row), `settings` (key/value).

Article status flow:
```
new → scored → summarized → liked | disliked | dismissed
           └→ hidden  (score < threshold, skip summarization)
```
`dismissed` is only set in bulk via `POST /dismiss-all` (the per-article dismiss button is removed). Votes are kept in the `votes` table even after dismiss.

`articles.clean_title` / `title_was_clickbait` hold the de-clickbaited headline (Settings → Reader → Headlines). **`articles.title` is never overwritten** — the original backs the FTS index and stays visible under the rewrite. The rewrite is only displayed when the setting is on *and* `title_was_clickbait=1`; `clean_title IS NULL` means "never processed", so pre-feature articles render unchanged. `routes._resolve_title()` is the single place that decides.

`articles.feed_content` stores the feed-provided body (`<content:encoded>` for RSS, `<content>` for Atom — feedparser unifies both into `entry.content[0].value`). Used as a fallback when trafilatura's HTTP fetch returns nothing. `articles.read_at` is set when the user first opens the reader modal.

## Accounts and roles
Registration is **open**, and the **first account created becomes admin**; the
rest are plain users. The first registration *claims the bootstrap owner row*
rather than creating a parallel account, so pre-accounts reading history stays
attached.

Feeds, articles and scores are shared. Read state, saves and votes are per-user
(`user_article_state`, `votes.user_id`). The preference profile is shared —
readable by everyone, writable by admins.

`@admin_required` covers settings, feed management, pipeline triggers and user
admin. **Hiding a control in a template is not gating a route — do both**;
`tests/test_auth.py` asserts a plain user gets 403 from every admin route.

HTMX fragments get `401` + `HX-Redirect` rather than a `302`, or the login page
gets swapped into `#article-list`.

## Routes
- `GET /` `GET /settings` — pages
- `GET /articles` `GET /feeds` `GET /count` — HTML fragments
- `POST /vote/<id>/<1|-1>` — like/dislike per article
- `POST /dismiss-all` — bulk-mark every currently-listed article as `dismissed`. Honors `?feed=<id>`.
- `POST /article/<id>/dismiss` — single-article dismiss; gesture-only (no UI button), fired by swipe-left on `.article-row`.
- `GET /article/<id>/content` — reader modal fragment (marks `read_at`)
- `POST /poll` — kicks off poll + pipeline in a background thread
- `GET /status` — pipeline status (HTML fragment, or JSON if `Accept: application/json`)
- `GET|POST /preferences` — profile text view/edit
- `POST /preferences/regenerate` — rebuild profile from votes (background thread)
- `GET|POST /settings/models` — choose scoring/summary models from `ollama_client.list_models()`
- `GET|POST /login` `GET|POST /register` `GET|POST /logout` — public
- `GET /profile` `POST /profile/password` — any user
- `GET /admin/users` `POST /admin/users/<id>/{role,delete,reset-password}` — **admin**
- `GET|POST /settings/titles` — toggle `declickbait_enabled` (headline rewriting)
- `GET|POST /settings/content` — `content_filter_mode` (`off`/`highlight`/`remove`) + `content_filter_llm`
- `GET|POST /settings/ollama` — set the Ollama host/port at runtime (overrides `OLLAMA_HOST`)
- `GET|POST /settings/models` — pick a model per job, from what Ollama reports installed
- `POST /settings/ollama/test` — probe the host/port **currently in the form**, without saving
- `GET|POST /feeds/opml` — OPML export (GET) / import (POST file upload)
- `POST /feeds/<id>/tags` — save comma-separated tags; sidebar groups feeds by tag.

## LLM notes
- **Six distinct jobs use Ollama**: relevance scoring (batched, JSON), article summaries (plus the clickbait rewrite — same request), video transcript summaries, padding detection (JSON), preference-profile rebuild, and the "what you missed" digest. Each takes its model from `llm_config.model_for(db, action)`, resolving per-action setting → legacy `scoring_model`/`summary_model` → env default.
- The Settings panel lists the models Ollama actually reports and **flags a configured model that is not installed** — that exact mismatch (`ministral-3:14b`) made every scoring call fail silently for six weeks.
- **Endpoint resolution:** `pipeline.ollama_base(db)` is the single source of truth — Settings override, else the `OLLAMA_HOST` env var. It is read *per call*, so a change in Settings applies on the next scheduled job with no restart. `ollama_client` itself stays free of app state: `generate()` / `list_models()` / `probe()` take an optional `base_url` and fall back to the env constant.
- `ollama_client.compose_base_url(host, port)` validates and builds the URL; it raises `ValueError` with UI-ready messages. `probe()` is `list_models()` that reports *why* it failed instead of returning `[]` — use it for anything user-facing.
- **De-clickbait rides on the summarization call.** With `declickbait_enabled`, `summarize_scored_articles` swaps `summarization_prompt` for `summarization_with_title_prompt` and asks for `{summary, was_clickbait, clean_title}` in one JSON response — no extra Ollama calls. **Invariant: a malformed response must never cost the summary.** On unusable JSON it retries once with the plain-text prompt and stores `clean_title=NULL`. If you add a fourth field here, keep that fallback: two JSON fields from a 3b model is already the reliability ceiling.
- **Aside detection (pass 2) is a separate call**, behind `content_filter_llm`, and best-effort: summarization has already succeeded when it runs, so any failure returns `None` and the reader falls back to the regex pass. Results are stored in `articles.aside_spans` as *content fingerprints*, not character offsets — `full_text` is immutable but the block-splitting between it and the page is render-time logic that may change.
- `pipeline._clean_title_from()` rejects rewrites that are empty, unflagged, unchanged, or over `MAX_CLEAN_TITLE_CHARS` — every rejection degrades to the original title.
- **`clean_title` is not in the FTS index.** Adding it means rebuilding `articles_fts` plus all three triggers together; deferred to the Postgres migration where it's one line on a generated column (see `docs/feature-plan.md` §0.3). Search matches the original wording, which is usually what you remember anyway.
- Scoring uses `format:"json"` Ollama param to constrain output to valid JSON.
- Article content is wrapped in XML delimiters (`<article_snippet>`, `<article_content>`) to mitigate prompt injection.
- `generate()` returns `None` on failure — all callers must handle `None` gracefully (skip, log, continue). It retries on `ConnectError`/`TimeoutException` up to `MAX_RETRIES`.
- **Batched scoring.** `SCORING_BATCH_SIZE` (default 8) scores several articles per call. A batch is only accepted if *every* requested id comes back — a partial answer means the model lost track, and trusting it silently leaves articles unscored. Anything unusable falls back to one call per article. `SCORING_BATCH_SIZE=1` reproduces the original behaviour exactly.
- `pipeline_runs` records every run (counts, duration, lock skips) and feeds `/insights`.
- Ollama calls are serialized intentionally — concurrent requests contend for GPU VRAM.

## Frontend
- Single HTML page + HTMX (CDN). No build step, no React.
- `GET /articles` and `GET /feeds` return HTML fragments, not full pages.
- Vote uses `hx-post` / `hx-swap` — no page reloads.
- After clicking Refresh, the index page polls `/status` every 3s and re-fetches `/articles` when `last_pipeline_run_at` advances.
- Reader modal is a `<dialog>`: title (large) → description (medium) → content (regular). `_clean_content` strips a leading body line that duplicates the title or description.
- **Article padding** (Settings → Reader → Article padding). `content_filter.classify_lines()` tags lines as `related_links` / `promo` / `older_news`; `routes._group_blocks()` collapses consecutive tagged blocks into one `<details>`. **Both `highlight` and `remove` only fold — nothing is ever dropped**, so a misclassification is one click away. Default is `remove`, which matches what `_clean_content` used to do destructively.
- Only *section boundaries* (`Related`, `Otras noticias`, …) truncate to end-of-body. Promotional one-liners (`Advertisement`, `Sign up`) are marked individually — they appear mid-article, and treating one as a boundary would discard the reporting after it.

## Tests
```
docker compose run --rm web pytest tests/ --cov=app
```
Ollama and feedparser are mocked. Postgres is **not** — there is no in-memory mode, so tests create and drop a throwaway database each, which means every run exercises the real DDL. Point `TEST_DATABASE_URL` at a server. Coverage target is 100%.

## Retention
`retention_days` (default 15) prunes articles past the window. **Ships inert** —
`retention_confirmed` must be set in Settings first, because the default window
is shorter than most existing corpora and the first run would otherwise delete
nearly everything. Favorites are never pruned; votes carry title/summary
snapshots so the preference profile survives any amount of pruning.

Retention keys on `created_at` (ingest time), never `published_at` — feeds carry
wrong and future publication dates.

## Migrating from the old SQLite database
```
python scripts/import_sqlite.py --sqlite data/rss.db --dry-run   # counts only
python scripts/import_sqlite.py --sqlite data/rss.db
```
Never writes to the SQLite file — keep it, it is the rollback.

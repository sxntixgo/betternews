# Better News — Codebase Guide

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
- `app/prompts.py` — The LLM prompts. **Templates, not prose**: `scoring_prompt` interpolates six values and dropping one does not raise — it renders a prompt that still looks reasonable, still returns a confident score, and no longer contains the article.
- `app/prompt_overrides.py` — the parts a reader may edit in Settings (`scoring_rules`, `kinds`, `tag_range`, `profile_framing`) and the machinery that stops them breaking anything. `validate()` does not inspect the slot in isolation: it renders the **real** scoring prompts with the edit applied and checks the invariants survived — the `<article_snippet>` delimiters (a prompt-injection boundary) and the JSON shape the parser depends on. A slot is interpolated into a template, so the only honest way to know an edit did no damage is to build the thing and look. Empty resets to the default, so there is no way to end up with no prompt. **`SCORING_RULES` is shared by the single and batch scorers on purpose**: subject match is the primary signal, style/format/"depth" is a minor tiebreaker that must never push a stated interest below 0.5. That hierarchy is not decoration — without it the scorer gave **0.00 to a tournament named in the reader's own profile**, justifying it as "no tactical depth". For the same reason `profile_prompt` is forbidden from describing writing style: it used to ask for it, and that is where the style criteria came from.
- **Measure scoring changes, do not eyeball them.** `scripts/backtest_scoring.py` re-scores every article the reader has voted on and reports agreement before/after; votes are labelled data and nothing was checking against them. Baseline when it was written: **65% agreement, 11 of 39 liked articles scored below the threshold and hidden, 0 of 4 dislikes correctly scored low.**
- `app/llm_config.py` — **the registry of every Ollama job** and which model runs it. Adding a `generate()` call means adding an Action here; `tests/test_llm_config.py` fails if a prompt builder is not registered.
- `app/content_filter.py` — Detects article padding (related rails, promos, older-news recaps). Pass 1 is regex at render time; pass 2 is an optional LLM call stored as fingerprints.
- `app/api/` — **the JSON API**, `Blueprint("api", url_prefix="/api/v1")`. A separate blueprint on purpose, not content negotiation: one function serving two representations couples them, and the HTML path's session assumptions leak into the JSON path. Every response is serialized through `app/presenters.py` — never a raw row — so the browser and a phone cannot drift about which headline to show. Errors are JSON at every status, including 404/405, which need app-level handlers (`api.install`) because an unmatched URL never reaches a blueprint.
- `app/api/auth.py` — password sign-in for clients that can hold a cookie. Sets the Flask session; returns **no token**. Reuses the HTML login's lockout, because a second password path with its own rules is how brute-force protection stops applying to half the front door.
- `app/api_tokens.py` — per-device bearer tokens, SHA-256 hashed (high-entropy random needs no slow KDF, and a slow one would run on every request). `@api_auth` accepts a bearer token **or** the browser session — a phone cannot hold a cookie, a browser should not hold a token. Bearer wins when both are present, and a *malformed* `Authorization` header is a 401 rather than a silent fallback. `SameSite=Strict` is what makes cookie auth safe here; it replaced the bearer-only rule. Note `app.config.setdefault` does **not** work for cookie flags — Flask already defines those keys, so the SameSite it appeared to set was silently dropped for months. `auth._is_api_request()` exempts `/api/` from the session guards — without it the app-wide `before_request` answered every API call with a 302 to `/login`, valid token or not.
- `@api_admin` — role check on top of `@api_auth`, which only proves *who*. `/poll` and `/rescore-hidden` are admin-only on the HTML side, and a reader who could kick the pipeline from a phone would be a quiet privilege escalation. Answers 403 as JSON.
- `app/api/settings.py` — the seven settings panels, admin-only. **Fourteen bespoke endpoints on purpose, not a generic `PUT /settings/{key}`**: half of them are not stores at all (`ollama/test` probes without saving, `retention/prune` deletes rows, `models/recommended` computes, `topics` writes a different table), so a generic endpoint would need a special case for most of them and would accept a typo'd key nothing ever reads. `settings/reader` covers four HTML panels in one call — one screen's worth of toggles, and a client making four requests to draw one section would be paying for the server's template layout. Both front ends read the same `settings` table, so they cannot disagree while both exist.
- `app/api/admin.py` — user admin, insights, and the Ollama call log. The guard rails are re-implemented rather than shared with the old HTML routes (which returned fragments and took form fields), but the *rules* must not diverge and are asserted separately: the last admin cannot be demoted or deleted, and you cannot delete yourself. `GET /insights` answers all seven panels in one call — they are only ever read together.
- **The API now covers everything.** `docs/api-and-spa-plan.md` B.4 said settings, admin and insights would never be ported; that was reversed by `docs/plans/2026-08-01-spa-parity-and-password-login-plan.md`, which is done.
- `app/views/` — **what is left of the server-rendered UI: four routes.** `accounts.py` has `/login`, `/register`, `/logout`; `ops.py` has `/health`. Nothing else. A browser with no session needs somewhere to land that does not depend on the SPA bundle having loaded, and the container healthcheck curls a URL rather than holding a token. `tests/test_app_factory.py` asserts that set **exactly** — a fifth route creeping back is how two UIs start disagreeing again. Everything a reader does is `app/api/` plus the SPA in `web/`.
- `app/presenters.py` — **what the reader sees**, decided once for every client: which headline after de-clickbait (`resolve_title`), which passages fold as older-news padding (`content_blocks`), reading time, the row → card mapping. Imports no Flask and touches no request context, enforced by `tests/test_presenters.py`, because a mobile client has neither. Put anything here that decides *what* is shown; leave *how* it is marked up to the templates. A view function that formats for display is in the wrong file.
- `app/auth.py` — accounts, sessions, password rules and lockout. **No decorators and no request hooks**: every surviving HTML route is public, so they had nothing to guard, and `_force_password_change` pointed at a profile page that no longer exists. `@api_auth` / `@api_admin` do that job now.
- `app/tags.py` — feed tag normalisation. `feeds.tags` is a comma-separated Text column, **not an array**; `list()` on it iterates characters, which is exactly what the first API serializer did. Lives outside `app/views/` because the tag a client types and the tag the sidebar groups by must be the same string.
- `app/feeds.py` — feedparser polling. `poll_all_feeds(app)` is the entry point.
- `app/scheduler.py` — APScheduler wiring. Jobs registered here.
- `app/digest.py` — the "what you missed" briefing. Per-user (unread is per-user), cached against a fingerprint of the unread set so it only regenerates when that set changes.
- `app/extract.py` — ordered extraction chain; the winning rung is stored on `articles.extract_source`.
- `app/export.py` — Markdown/zip export, scoped to the calling user.
- `app/affinity.py` — **the reader's own votes as a scoring signal, and the strongest one there is.** Measured on 2,149 real votes, held out 5-fold: the LLM relevance score separated likes from dislikes at **AUC 0.524** (a coin flip); per-topic like-rates managed **0.756**. A 50/50 blend scored 0.632 — *worse than affinity alone* — which is why `adjust()` replaces the score rather than nudging it. Guards matter: below 40 votes, or 8 of either kind, it returns `{}` and stays out of the way, because a reader with only likes gives every topic a smoothed rate of 1.0 and that flattens the ranking entirely.
- `app/kinds.py` — **the second tagging axis: what kind of story, not what it is about.** A *closed* vocabulary (fixture, live, match-report, transfer, interview, analysis, service, listicle, news), unlike topics, because a kind is only useful if the same article shape gets the same label every time. It exists because topic affinity could not separate `boca-juniors`: 28 likes, 30 dislikes, 48% — noise — since it holds both fixture listings and transfer news. Broadcast-listing pieces run a **12.5% like-rate against 39.4%** for everything else. `affinity.KIND_WEIGHT = 0.45` splits the score between the two axes; swept on real votes, the plateau is 0.40–0.50.
- **Tags are the training data.** Affinity predicts at AUC 0.657 on a one-tag article, 0.752 on two, 0.780 on three or four — and rare/specific tags carry twice the signal of common ones. The prompts ask for 4-8 with at least two specific, and the "known topics" list is explicitly *not* a menu: it used to show the 20 most common tags and say "prefer" them, which pushed toward exactly the generic tags that carry least signal.
- `votes.topics_snapshot` — topics as they were when the vote was cast. On the vote, not read back off the article, for the same reason as `title_snapshot`: retention deletes articles and `article_id` goes NULL, so affinity would silently decay every time the pruner ran.
- `app/topics.py` — topic slugs + the **admin** mute/boost rules, which change the stored score for everyone.
- `app/user_topics.py` — **per-user** topic stances. Scores are shared, so these cannot re-score anything: they filter and reorder one user's list at read time via `NOT_HIDDEN_SQL` / `BOOST_SQL`, applied in `repo.articles` and `digest`. Any new article-listing query must apply them too, or the list and the unread count disagree.
- `app/insights.py` — ranking-accuracy queries behind `/insights`.
- `app/health.py` — feed auto-recovery + the ingestion-aware `/health`.
- `app/call_log.py` — records each Ollama request and response to `ollama_calls`, off by default, bounded to the most recent 200. `/ollama-log` shows both sides. The web and worker are separate processes, so this goes to the database; an in-memory buffer would be invisible to whichever one serves the page.
- `app/pipeline_status.py` — why the reading list is empty. Ordered by what the reader should act on first: no feeds, then Ollama unreachable, then a model that is not installed, then simply waiting, then everything hidden, then caught up. The list only shows `status='summarized'`, so poll -> score -> summarize must all complete before anything appears; a blank page for every one of those states is how a misconfigured model went unnoticed three times.
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

`@api_admin` covers settings, feed management, pipeline triggers, user admin,
insights and the call log. **Hiding a control in the SPA is not gating an
endpoint — do both**; `tests/test_api.py` asserts a plain reader gets a JSON 403
from every admin endpoint, parametrised so a new one cannot be forgotten.

There are no `login_required` / `admin_required` decorators and no app-wide
session hooks any more: every surviving HTML route is public by design, so they
had nothing left to guard. `_force_password_change` went with them — it
redirected to `main.profile`, which no longer exists. `/api/v1/me` reports
`must_change_password` and the SPA refuses to render the reading list until it
is cleared.

## Routes

**HTML — four, and that is the whole list** (asserted exactly in `tests/test_app_factory.py`):
- `GET|POST /login` `GET|POST /register` `GET|POST /logout` — public
- `GET /health` — public; the container healthcheck curls it

**JSON — `/api/v1`, 60 routes**, in `app/api/`: `articles` (list, detail, vote,
save, dismiss, dismiss-all, search, export), `feeds` (+ OPML), `me` (password,
tokens, preferences), `auth` (login, register, logout), `topics`, `digest`,
`status`, `poll`, `rescore-hidden`, `settings` (14), `admin` (users, insights,
ollama-log).

Read `shared/api.ts` for the shapes — `tests/test_api_contract.py` parses it and
asserts the API sends exactly those fields, so a rename cannot silently break
both clients.

## LLM notes
- **Six distinct jobs use Ollama**: relevance scoring (batched, JSON), article summaries (plus the clickbait rewrite — same request), video transcript summaries, padding detection (JSON), preference-profile rebuild, and the "what you missed" digest. Each takes its model from `llm_config.model_for(db, action)`, resolving per-action setting → legacy `scoring_model`/`summary_model` → env default.
- The Settings panel lists the models Ollama actually reports and **flags a configured model that is not installed** — that exact mismatch (`ministral-3:14b`) made every scoring call fail silently for six weeks.
- **`generate()` follows redirects.** Without that, putting a reverse proxy in front of Ollama that upgrades HTTP to HTTPS makes every call fail with a 308 and nothing but a log line to show for it.
- **A run reporting `0 scored` in ~0s is a failing run, not an idle one.** Failures return fast, and batching means few calls, so a broken model completes the whole pipeline in under half a second. `pipeline.last_llm_error()` records why; `/insights` and the empty reading list both show it.
- **Endpoint resolution:** `pipeline.ollama_base(db)` is the single source of truth — Settings override, else the `OLLAMA_HOST` env var. It is read *per call*, so a change in Settings applies on the next scheduled job with no restart. `ollama_client` itself stays free of app state: `generate()` / `list_models()` / `probe()` take an optional `base_url` and fall back to the env constant.
- `ollama_client.compose_base_url(host, port)` validates and builds the URL; it raises `ValueError` with UI-ready messages. `probe()` is `list_models()` that reports *why* it failed instead of returning `[]` — use it for anything user-facing.
- **De-clickbait rides on the summarization call.** With `declickbait_enabled`, `summarize_scored_articles` swaps `summarization_prompt` for `summarization_with_title_prompt` and asks for `{summary, was_clickbait, clean_title}` in one JSON response — no extra Ollama calls. **Invariant: a malformed response must never cost the summary.** On unusable JSON it retries once with the plain-text prompt and stores `clean_title=NULL`. If you add a fourth field here, keep that fallback: two JSON fields from a 3b model is already the reliability ceiling.
- **Aside detection (pass 2) is a separate call**, behind `content_filter_llm`, and best-effort: summarization has already succeeded when it runs, so any failure returns `None` and the reader falls back to the regex pass. Results are stored in `articles.aside_spans` as *content fingerprints*, not character offsets — `full_text` is immutable but the block-splitting between it and the page is render-time logic that may change.
- `pipeline._clean_title_from()` rejects rewrites that are empty, unflagged, unchanged, or over `MAX_CLEAN_TITLE_CHARS` — every rejection degrades to the original title.
- **`clean_title` is not in the FTS index.** Adding it means rebuilding `articles_fts` plus all three triggers together; deferred to the Postgres migration where it's one line on a generated column (see `docs/feature-plan.md` §0.3). Search matches the original wording, which is usually what you remember anyway.
- Scoring uses `format:"json"`, but **that does not constrain reasoning models**. `gpt-oss` and similar emit their chain of thought into the same response field with the answer after it, so `_validate_json` scans for a balanced JSON object rather than requiring the whole response to parse. It scans from the *last* opening brace backwards: reasoning frequently quotes the schema it was asked for, and the real answer comes last.
- **Reasoning models need care.** `generate()` sends `think: false` alongside `format:"json"` (retrying without it if the server objects), and falls back to the `thinking` field when `response` comes back empty. Even so, a model that reasons at length can exhaust its output budget before emitting the JSON. Prefer a non-reasoning model for scoring and padding detection; reasoning is only worth its cost for the digest and the preference profile.
- The call log keeps the **tail** of a long response as well as the head, because that is exactly where a reasoning model puts its answer.
- Article content is wrapped in XML delimiters (`<article_snippet>`, `<article_content>`) to mitigate prompt injection.
- `generate()` returns `None` on failure — all callers must handle `None` gracefully (skip, log, continue). It retries on `ConnectError`/`TimeoutException` up to `MAX_RETRIES`.
- **Batched scoring.** `SCORING_BATCH_SIZE` (default 8) scores several articles per call. A batch is only accepted if *every* requested id comes back — a partial answer means the model lost track, and trusting it silently leaves articles unscored. Anything unusable falls back to one call per article. `SCORING_BATCH_SIZE=1` reproduces the original behaviour exactly.
- `pipeline_runs` records every run (counts, duration, lock skips) and feeds `/insights`.
- Ollama calls are serialized intentionally — concurrent requests contend for GPU VRAM.

## Frontend
- **`web/` is the reader**: Vite + React + TypeScript, served at `/` by Caddy. `shared/api.ts` is the one API contract, imported by both `web/` and `mobile/`.
- **`web/src/index.css` is the design system** — ~30 tokens taken from `job-application-tracker` (structure *and* palette: warm neutrals, not pure white/black). **`App.css` contains no hex literal and no literal radius**, and `e2e/design-system.spec.ts` asserts both, plus that every `var(--token)` used is actually defined — a typo there is silent, the property just does not apply.
- **`components/Modal.tsx` is the only modal.** Nine screens hand-rolled one, none with `role="dialog"`, `aria-modal`, a focus trap or focus restoration. Its focus trap filters to elements with a layout box: the OPML `<input type="file">` is `display:none`, matches the focusable selector, sorts last, and can never take focus — so the wrap never fired and Tab walked out of the dialog.
- **Every action needs a visible control**, not only a command-palette entry. Sign-out, Settings, Users, Insights, the Ollama log and Manage feeds were all palette-only at one point, which put the whole admin surface behind a shortcut. `design-system.spec.ts` asserts each is clickable without the palette, that a plain reader sees none of the admin ones, and that no icon-only button is nameless.
- **The PWA is real again**: `public/manifest.webmanifest`, `public/sw.js` (app shell only — offline *reading* is still deferred, D2), and a production-only registration in `src/pwa.ts`. Registering on the dev server caches module URLs Vite is rewriting, and Playwright reuses a developer's own server.
- Caddy sends `/api`, `/login`, `/register`, `/logout`, `/health` and `/static` to Flask; **everything else is the SPA**, so a deep link the SPA owns gets the SPA's routing rather than Flask's 404. `~/Dev/homestack/caddy/Caddyfile`.
- `vite.config.ts` builds with `base: '/'`. It used to be `/app/` while both UIs coexisted; leaving that would emit asset URLs nothing serves.
- The only `localStorage` key is `theme`. Auth is an HttpOnly + `SameSite=Strict` cookie the page cannot read, which is why the shell asks `/api/v1/me` whether it is signed in rather than looking.
- **An empty list says why.** `GET /api/v1/articles` carries a `diagnosis` on an empty *first* page — `no_feeds`, `ollama_unreachable`, `model_missing`, `processing`, `all_hidden`, `caught_up` and so on. A bare "Nothing to read" is how a misconfigured model went unnoticed three times. The server decides the wording and whether it is admin-only; the client decides which screen the button opens, because the server has no idea this client is modal-based.
- Charts on `/insights` are hand-rolled SVG (`web/src/components/BarChart.tsx`). `react` and `react-dom` are the only dependencies and it stays that way — a charting library is 100 KB+ for six charts on a screen visited monthly.
- **Article padding** (Settings → Reading → Article padding). `content_filter.classify_lines()` tags lines as `related_links` / `promo` / `older_news`; `presenters.group_blocks()` collapses consecutive tagged blocks into one foldable group. **Both `highlight` and `remove` only fold — nothing is ever dropped**, so a misclassification is one click away.
- Only *section boundaries* (`Related`, `Otras noticias`, …) truncate to end-of-body. Promotional one-liners (`Advertisement`, `Sign up`) are marked individually — they appear mid-article, and treating one as a boundary would discard the reporting after it.

## Tests

Four suites, and it matters which is which:

| Suite | Command | Crosses the network? |
|---|---|---|
| Backend | `docker compose run --rm web pytest tests/` | Flask test client, real Postgres, Ollama mocked |
| Web (mocked) | `cd web && npm run e2e` | No — the API is stubbed with `page.route` |
| Web (live) | `export BN_E2E_TOKEN=$(scripts/e2e-token.sh) && cd web && npm run e2e:live` | **Yes** — browser → proxy → Flask → Postgres |
| Mobile | `cd mobile && npm test` | No — pure functions only |

CI runs the first, second and fourth on every push and pull request
(`.github/workflows/ci.yml`). Actions is free without a minute limit here
because the repository is public — the 2,000-minute allowance applies to private
ones. The live suite is not in CI: it needs a running stack and a real token,
and faking either would defeat the only thing it is for.

**The live suite exists because the others share a blind spot.** An app-wide
session guard once answered every `/api/v1` call with a 302 to `/login`, valid
token and all, and a thousand passing tests saw nothing: the Python test client
was already signed in, and the web tests never reached Flask. Re-introducing
that bug fails all six live tests. It skips loudly without `BN_E2E_TOKEN`, since
a live suite that quietly passes with nothing running is worse than none.

`tests/test_api_contract.py` parses `shared/api.ts` and asserts the API sends
exactly those fields, so a rename in `app/api/serializers.py` cannot silently
break both clients.

`npm run typecheck` covers **both** `src/` and `e2e/`. It did not cover `e2e/`
for a long time, and the fixtures say at the top that their shapes mirror
`shared/api.ts` "so a contract change breaks these too" — which was true of
nothing but a human reading it. Adding a required field to `Me` left the
fixtures happily claiming to be a `Me` that lacked it.

`tests/test_app_factory.py` refuses **duplicate test function names** across
every test file. A redefined test silently replaces the first one: Python
rebinds the name, pytest collects the survivor, and the lost test takes its
coverage with it. That is how it was noticed — one line of `app/api/feeds.py`
went uncovered with no failing test to explain why.

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

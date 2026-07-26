# Better Read

A single-user, self-hosted RSS reader with **LLM-powered relevance ranking**. It polls your feeds, uses a local [Ollama](https://ollama.com/) model to score each article against a profile it learns from your likes/dislikes, and surfaces what's actually worth reading — with generated summaries so you can decide fast.

Flask + HTMX, no build step, SQLite storage, runs in Docker.

## Features

- **LLM relevance scoring** — every article is scored 0–1 against a preference profile; low-scoring items are hidden automatically.
- **Learned preferences** — the profile is rebuilt from your like/dislike votes, so ranking improves as you use it.
- **Generated summaries** — articles above the threshold get an LLM summary.
- **HTMX-first UI** — single page, fragment updates, no page reloads, no JavaScript framework.
- **Feed management** — tag/group feeds in the sidebar, OPML import & export.
- **Reader mode** — in-app reader modal with full-text extraction ([trafilatura](https://trafilatura.readthedocs.io/)), falling back to feed-provided content.
- **PWA-ready** — manifest + service worker for install-to-homescreen.
- **Background polling** — APScheduler polls feeds and runs the scoring/summary pipeline on an interval.
- **Padding removal** — related-story rails, newsletter pitches and older-news recaps are folded away in the reader. Collapsed, never deleted.
- **Clickbait-free headlines** — optional: the summarizer rewrites headlines that withhold their point, and shows the original underneath. Costs no extra LLM calls.
- **Prompt-injection aware** — article text is wrapped in XML delimiters and scoring is constrained to JSON output.

## Architecture

```
Browser (HTMX) ──► Flask app ──► SQLite (./data/rss.db)
                       │
                       ├─ APScheduler ──► feedparser (poll feeds)
                       └─ pipeline ─────► Ollama (score + summarize)
```

- **Flask app** in Docker serving HTML fragments.
- **Ollama** runs on the host (or any reachable host) and does all the LLM work.
- **SQLite** persists feeds, articles, votes, preferences, and settings in `./data`.

See [`CLAUDE.md`](CLAUDE.md) for a detailed codebase guide (key files, routes, DB schema, article status flow).

## Requirements

- Docker + Docker Compose
- [Ollama](https://ollama.com/) running and reachable, with at least one model pulled (e.g. `ollama pull llama3.2:3b`)

> Ollama must listen on all interfaces so the container can reach it. Set `OLLAMA_HOST=0.0.0.0:11434` in the environment **before** starting Ollama.

## Quick start

```bash
git clone https://github.com/sxntixgo/rss-reader.git
cd rss-reader

cp .env.example .env      # then edit .env — at minimum set FLASK_SECRET_KEY and OLLAMA_HOST

docker compose up --build
```

The app is served on **http://localhost:5001** (mapped from the container's port 5000 in `docker-compose.yml`).

## Configuration

Copy `.env.example` to `.env` and adjust. Key variables:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama endpoint reachable from the container (overridable in Settings) |
| `OLLAMA_TIMEOUT` | `180` | Seconds per Ollama call; bump for larger models |
| `SCORING_MODEL` | `llama3.2:3b` | Model used for relevance scoring (overridable in Settings) |
| `SUMMARY_MODEL` | `llama3.2:3b` | Model used for summaries (overridable in Settings) |
| `SCORE_THRESHOLD` | `0.35` | Articles below this score are hidden |
| `POLL_INTERVAL_MINUTES` | `30` | How often feeds are polled |
| `FLASK_SECRET_KEY` | — | **Set this to a random string** |

Additional tuning vars (`SCORING_SNIPPET_CHARS`, `LOG_FORMAT`, `DB_PATH`/`BACKUP_DIR`/`KEEP`) are documented in `CLAUDE.md`.

### Hiding article padding

**Settings → Reader → Article padding** controls what the reader does with
related-story rails, newsletter pitches and recaps of older coverage:

| Mode | Behaviour |
|---|---|
| `remove` (default) | Folded into a `N sections hidden — show` line |
| `highlight` | Framed and labelled, collapsed |
| `off` | Everything rendered inline |

**Nothing is ever deleted** — both active modes only collapse, so a misjudged
paragraph is always one click away. Pattern matching handles the formulaic cases
for free. The optional *"use the LLM to spot older-news recaps"* checkbox catches
the semantic ones at the cost of **one extra Ollama call per article**.

### Rewriting clickbait headlines

**Settings → Reader → Headlines** turns on headline rewriting. The summarizer judges
whether a headline withholds its point to force a click and, if so, rewrites it to
state what the article reports — reusing the summarization call, so it costs nothing
extra. The published headline is never overwritten: it stays in the database and is
shown beneath the rewrite, so you can always see what changed. Only headlines the
model flags are touched, and it applies to articles summarized from then on.

### Changing the Ollama endpoint without a rebuild

**Settings → Ollama → Connection** sets the host and port at runtime, overriding
`OLLAMA_HOST`. **Test connection** probes the values in the form *before* saving and
reports what it found — reachable and how many models are installed, or the actual
error ("connection refused", "timed out", an HTTP status). Clear both fields to fall
back to the environment variable. Changes apply on the next pipeline run; no restart.

## Usage

1. Add feeds (or import an OPML file) from the **Manage Feeds** page.
2. Click **Refresh** to poll feeds and run the pipeline; the page auto-updates as scoring completes.
3. **Like / dislike** articles to teach the ranker, then regenerate the profile from Preferences.
4. Tag feeds to group them in the sidebar.

## Development

Run the test suite (Ollama and feedparser are mocked — no live services needed):

```bash
pytest tests/ --cov=app
```

## Backups

`scripts/backup.py` makes timestamped copies of the SQLite DB (configurable via `DB_PATH`, `BACKUP_DIR`, `KEEP`).

## License

No license specified yet.

# SPA parity and password login

## Goal

Two things, in this order because the first is small and the second is long:

1. **Sign in with a username and password.** Pasting a token is a developer's
   login, not a reader's. The SPA takes credentials and mints the token itself.
2. **Full parity with the server-rendered UI** — all 72 routes, Settings and
   Admin included — so the HTMX frontend can be deleted rather than kept
   alongside forever.

**Success criteria.** A reader signs in with their username and password, and
every task they can do at `news.lan` they can do at `news.lan/app`: read, search,
vote, manage feeds, change every setting, administer users, read insights. The
HTMX reading templates are gone, and `npm run e2e:live` passes against the real
stack.

## Where this starts from

```
API today        11 endpoints, bearer-only, contract-tested against shared/api.ts
SPA today        sign-in (paste token), list, reader, sidebar, vote/save
HTML today       72 routes across 6 view modules
```

The earlier plan (`docs/api-and-spa-plan.md` B.4) deliberately excluded Settings,
Admin and Insights from the API. **That decision is now reversed** — this plan
supersedes it. Worth knowing why it was made: those are 34 of the 72 routes and
are visited monthly from a desktop. Reversing it roughly triples the work, and
the honest reason to accept that is that two frontends forever is worse than one
expensive migration.

---

## Phase 1 — Password login  ·  **Opus** (auth) → **Sonnet** (screen)

The smallest slice that delivers real behavior, and independent of everything
else. Ships alone.

### 1.1 `POST /api/v1/auth/login`  ·  **Opus**

**What.** Username and password in, `{token, user}` out. Mints an `api_tokens`
row named after the client (`"web app"`), so it appears on the profile page
beside any others and can be revoked per device.

**Where.** New `app/api/auth.py`, registered like the other API modules.

**Reuse, do not reimplement.** `auth.is_locked_out`, `auth.record_failure`,
`auth.clear_failures`, `auth.verify_password` already exist and already back the
HTML login. A second password path that forgets the lockout is how brute-force
protection quietly stops applying.

- 401 on bad credentials, **429 when locked out** (15 minutes, `LOCKOUT_MINUTES`)
- Never say whether the username exists — the HTML form already gets this right
- `POST /api/v1/auth/logout` revokes the calling token, so signing out on a
  device actually invalidates it rather than only forgetting it locally

**Verify.** `tests/test_api.py`: correct credentials return a usable token that
authenticates a subsequent `/me`; wrong password 401s; six failures return 429;
a logged-out token stops working. Extend the anonymous-endpoint parametrisation
so login itself is reachable without a token — it must be the one exception.

### 1.2 Reuse-or-mint  ·  **Opus**

**What.** Decide whether login mints a new token every time or reuses one.

**Recommendation: mint one per login, named `web app`, and revoke the previous
`web app` token for that user.** Otherwise a reader who signs in weekly
accumulates a token list they will never prune, and revoking "the browser"
becomes guesswork.

**Verify.** Logging in twice leaves exactly one live `web app` token, and the
first token no longer authenticates.

### 1.3 SPA sign-in screen  ·  **Sonnet**

**What.** Replace the paste-a-token field with username and password. On
success store the returned token exactly as now.

**Where.** `web/src/screens/SignIn.tsx`, `web/src/api/client.ts`,
`shared/api.ts` (add `login`/`logout` to the client).

**Verify.** `web/e2e/auth.spec.ts` — wrong password shows the error at the form;
correct credentials reach the list; the password field is `type="password"`;
the token never appears in the DOM. Then `live.spec.ts` against the real stack
with real credentials.

### ⛔ Gate 1
Ship it. A reader can sign in properly, and everything below is additive.

---

## Phase 2 — API for the reading experience  ·  **Sonnet**

Fills the gaps the SPA needs before it can match the reading UI.

| Endpoint | Mirrors | Note |
|---|---|---|
| `GET /api/v1/search?q=` | `/search` | `repo.articles.search`, already user-scoped |
| `POST /api/v1/articles/dismiss-all` | `/dismiss-all` | takes the same filters — feed, hidden, saved, topic |
| `GET /api/v1/status` | `/status` | pipeline stamp + high-score notifications |
| `POST /api/v1/poll` | `/poll` | kicks the pipeline; returns immediately |
| `POST /api/v1/digest/dismiss` | `/digest/dismiss` | |
| `GET /api/v1/export?scope=` | `/export/markdown` | see the download problem below |
| `POST /api/v1/rescore-hidden` | `/rescore-hidden` | |

**The download problem.** `<a download>` cannot send an `Authorization` header,
so the export and OPML endpoints cannot be plain links in a bearer-auth SPA.
Fetch the body, build a `Blob`, and click an object URL — decide this once here
and reuse it for OPML in Phase 6.

**Verify.** Per endpoint in `tests/test_api.py`, plus extend
`tests/test_api_contract.py` with each new response type so `shared/api.ts` and
the serializers cannot drift.

---

## Phase 3 — SPA reading parity  ·  **Sonnet**

**What.** Search box (debounced, as the HTML one is), hidden view, saved view,
dismiss-all, the digest panel, topic chips that filter, and the Refresh button
with the status-polling dance that re-fetches when `last_pipeline_run_at`
advances.

**Where.** `web/src/App.tsx` and new components under `web/src/components/`.

**Verify.** Extend `web/e2e/` mocked specs: searching narrows the list; the
hidden view shows only hidden articles; dismiss-all greys every row without
removing it; a topic chip filters to that topic; the digest renders and
dismisses. Phone project included, since these are the screens that get used on
a phone.

---

## Phase 4 — SPA interaction parity  ·  **Sonnet**

The 628 lines of behaviour in `index.html` and `base.html` that are features,
not scaffolding. Each needs a port-or-drop decision, made explicitly:

| | |
|---|---|
| keyboard nav | `j`/`k`/`l`/`o`/`r` |
| swipe gestures | swipe-right like, swipe-left dismiss, pull-to-refresh |
| favicon badge | canvas-drawn unread count, `setAppBadge` for the PWA |
| notifications | high-score alerts, permission asked on first real click |
| theme | light/dark, persisted, redraws the favicon |
| reader embeds | lazy Twitter/Instagram hydration |

**Verify.** Playwright can drive keyboard and (via `page.touchscreen`) swipe.
The favicon is assertable the way the theme fix was — its `href` becomes a
`data:` URL. Notifications need `context.grantPermissions(['notifications'])`.
Anything genuinely untestable gets said so in the PR rather than claimed.

### ⛔ Gate 2
The SPA is now a complete *reader*. Everything below is administration, and a
reasonable person could stop here and keep Settings on the HTML side — revisit
before committing to Phases 5–8.

---

## Phase 5 — Accounts and profile  ·  **Sonnet**

**API.** `POST /api/v1/auth/register` (first account becomes admin, as the HTML
path does), `POST /api/v1/me/password`, `GET|POST /api/v1/me/tokens`,
`POST /api/v1/me/tokens/<id>/revoke`, `GET|POST /api/v1/me/preferences`,
`POST /api/v1/me/preferences/regenerate`.

**SPA.** A profile screen: account details, password change, topic stances,
the preference profile with its evidence line, and the token list.

**Verify.** Every endpoint refuses another user's data — mirror
`test_one_users_token_cannot_revoke_anothers`. Registration on an empty
instance yields an admin; the second yields a plain user.

---

## Phase 6 — Feed management  ·  **Sonnet**

**API.** `GET|POST /api/v1/feeds`, `DELETE /api/v1/feeds/<id>`,
`POST /api/v1/feeds/<id>/{pause,resume,threshold,tags}`,
`GET|POST /api/v1/feeds/opml`.

**Admin-only endpoints need an admin guard on the API side.** `@api_auth` only
proves *who*; there is no role check yet. Add `@api_admin` and mirror
`tests/test_auth.py`'s assertion that a plain user gets 403 from every admin
route — for every one of them, not a sample.

**SPA.** A manage-feeds screen: add, pause, delete, tags, per-feed threshold,
OPML in and out (reusing the Blob download from Phase 2).

**Verify.** A plain user is refused each admin feed endpoint; OPML round-trips
(export then import produces no duplicates — `ON CONFLICT DO NOTHING` already
covers the ingest, and this proves it).

---

## Phase 7 — Settings  ·  **Opus** (shape) → **Sonnet** (screens)

The largest phase: 21 routes over seven panels.

| Panel | Endpoints | Notes |
|---|---|---|
| Ollama connection | host, port, **test** | test probes without saving; keep that |
| Models | per-job model, recommendations, apply-all | needs the installed-model list and the "not installed" warning |
| Headlines | de-clickbait toggle | |
| Article padding | mode + LLM pass | |
| Retention | days, confirm, prune now, clear-read | destructive; keep the confirmations |
| Notifications | high-score threshold | |
| Topics | rules, mute/boost, tidy | |
| Embeds | toggle | |

**Shape decision (Opus).** These are key/value settings behind seven bespoke
forms. Resist a generic `PUT /api/v1/settings/{key}`: `ollama/test` probes
rather than saves, `retention/prune` deletes, `models/recommended` computes, and
`topics` writes a different table. A generic endpoint would need special cases
for half of them and would let a typo write a setting nobody reads.

**Verify.** Settings round-trip through the API and are visible in the HTML UI
(they share `settings`), so the two frontends cannot disagree while both exist.
Retention actions assert the confirmation is still required — `retention_confirmed`
exists precisely because the default window would delete most of a corpus.

---

## Phase 8 — Admin and ops  ·  **Sonnet**

**API.** `GET /api/v1/admin/users` and role/reset-password/delete;
`GET /api/v1/insights`; `GET /api/v1/ollama-log` plus toggle and clear.

**SPA.** A users screen, an insights screen, a call-log screen.

**Insights is the one with real UI cost.** It is seven query functions —
score histogram, agreement, threshold suggestion, per-feed, per-topic, recent
runs, pipeline health — currently rendered as server-side HTML. In the SPA they
need charts. Decide before starting: a small hand-rolled SVG bar chart is
probably enough and adds no dependency; a charting library is 100 KB+ for six
charts. **Recommendation: hand-rolled.**

**Verify.** A plain user gets 403 from every admin endpoint. The insights
numbers match the HTML page for the same database.

---

## Phase 9 — Cut over  ·  **Opus**

**What.** Caddy serves the SPA at `/`, the HTMX reading templates are deleted.

**Only after** Phases 1–8 are live and used for a week. This is the single
irreversible step in the plan.

**Where.** `~/Dev/homestack/caddy/Caddyfile` (drop the `/app` prefix, keep the
API on Flask); delete `templates/index.html` and the reading partials; delete
the view functions that only rendered them.

**What stays server-rendered regardless:** the login page (a browser needs
somewhere to land), `/health` (the container healthcheck curls it), and the
error pages.

**Verify.** The route-table diff again — the API and the surviving HTML routes
must be exactly what is intended, and nothing else. `npm run e2e:live` passes
against `/`. Coverage stays at 100% after the deletions.

---

## Risks and assumptions

**The token lives in `localStorage`, which XSS can read.** A session cookie
marked `HttpOnly` cannot be. The API is bearer-only by design — that is what
keeps a cookie from authenticating a cross-site request — so switching would
mean two auth models. For a self-hosted reader on a LAN, behind a private CA,
with one account, the bearer token is the right trade. **It is a trade, not a
non-issue**, and worth revisiting if this is ever exposed to the internet.

**Two frontends until Phase 9.** Every settings change must work in both, and
they share the `settings` table, so a bug in one is visible in the other. This
is the cost of not doing a big-bang rewrite, and it is the cheaper cost.

**The contract test only covers what it is told about.** Each phase must extend
`tests/test_api_contract.py`, or `shared/api.ts` drifts silently again.

**Phases 5–8 are where enthusiasm usually runs out.** They are administration
screens for one user. Gate 2 exists so that stopping there is an explicit
decision rather than an abandonment.

## Out of scope (YAGNI)

- Offline reading and a service worker — tracked separately as D2
- Real-time updates (SSE/websockets); polling already works
- Multi-user scoring: `articles.score` stays one shared column
- A native app screen for Settings — the phone is for reading
- Internationalising the SPA; the server-rendered UI is English-only too

## Open questions

1. **Does the SPA need `/register`?** The first account is created once, and
   after that registration is how a second reader joins. Cheap to add in Phase
   5; say so if you would rather it stayed server-rendered.
2. **Should `/app` become `/` in Phase 9, or should the SPA get its own
   hostname** (`read.lan`)? A separate host keeps both alive indefinitely, which
   is exactly what Phase 9 is meant to end.

## Model assignments

| Model | Tasks |
|---|---|
| **Opus** | 1.1 login endpoint · 1.2 token lifecycle · 7 settings API shape · 9 cut-over |
| **Sonnet** | 1.3 sign-in screen · 2 reading API · 3 reading parity · 4 interactions · 5 accounts · 6 feeds · 8 admin/ops |
| **Haiku** | `CLAUDE.md` updates after each phase |

Opus takes the auth model, the settings shape, and the deletion — the decisions
that are expensive or impossible to reverse.

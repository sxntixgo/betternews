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

## Design philosophy, borrowed from `job-application-tracker`

That project's conventions are deliberate and written down; three of them change
this plan rather than decorate it.

**No auth token in `localStorage`.** Its rule is explicit — *"No auth
tokens/secrets in localStorage. Sanctioned exception: the `theme` UI
preference."* Auth is an `HttpOnly`, `SameSite=Strict`, `Secure` cookie set by
the server, and its client says so at the top of `api.ts`: *"there is no token
to manage here."*

This **reverses Phase 1 below**, and it dissolves the objection I had raised.
I argued the API should stay bearer-only so a cookie could never authenticate a
cross-site request. `SameSite=Strict` is a better answer to the same problem:
the browser does not send the cookie cross-site at all, so there is nothing to
confuse the deputy with. The tracker gets CSRF safety without a CSRF token.

**Zero UI dependencies.** `react` and `react-dom`, nothing else — no component
library, no CSS framework. 123 CSS custom properties carry the design instead,
with semantic names (`--color-ink`, `--color-hairline`, `--stage-*`) and themes
switched by `data-theme` on `<html>`. Betternews is already here: the SPA has
the same two dependencies, and `static/style.css` already themes through
`--bg`, `--fg`, `--muted`, `--accent`, `--border`. **This also settles the
insights charts in Phase 8 — hand-rolled SVG, not a charting dependency.**

**Keyboard-first, and taught rather than hidden.** A command palette, a
shortcuts overlay on `?`, a global-shortcuts hook, and an `isEditableTarget`
guard so typing in a field never fires a shortcut. Betternews has `j`/`k`/`l`/
`o`/`r` and no way to discover them. **Phase 4 gains a palette and an overlay.**

Two more worth keeping: *"keep modules small and auditable"* — a stated goal,
not an aspiration — and theme as **System / Light / Dark**, where system follows
the OS. Betternews offers only a light/dark toggle today.

---

## Phase 1 — Password login  ·  **Opus** (auth) → **Sonnet** (screen)

The smallest slice that delivers real behavior, and independent of everything
else. Ships alone.

**Revised after reading the tracker.** The original version of this phase minted
a bearer token and put it in `localStorage`. It does not any more: the browser
gets an `HttpOnly` session cookie and never handles a credential at all. The
native app keeps bearer tokens, because a phone cannot use a cookie sensibly —
so the API ends up accepting **two** mechanisms, which is right, and is only one
in the tracker because it has no native client.

### 1.1 The API accepts a session cookie as well as a bearer token  ·  **Opus**

**What.** `@api_auth` currently reads `Authorization: Bearer` and *deliberately
never falls back to the session*. It now accepts either: bearer first, then the
Flask session.

**Where.** `app/api/__init__.py`, and `app/auth.py` for the cookie flags.

**The reason bearer-only existed is now handled better.** The worry was that a
browser sends cookies on cross-site requests, so a cookie-authenticated API is a
confused deputy. `SameSite=Strict` means the cookie is not sent cross-site at
all. Betternews is on `Lax` today, which already blocks cross-site POSTs;
**move it to `Strict`**, which costs nothing here — the SPA is same-origin, and
a cross-site *navigation* into a static page still works, it just arrives
logged-out until the page's own same-site fetches run.

**Verify.** Extend `tests/test_api.py`: the `anon` fixture (no cookie, no token)
still gets 401 from every endpoint; a session-authenticated client now gets 200
where it previously got 401 — **this is the assertion that inverts**, so update
`test_a_browser_session_does_not_authenticate_the_api` rather than delete it,
and say in its name what the new rule is. A bearer token still works with no
cookie present. `SESSION_COOKIE_SAMESITE` is asserted to be `Strict`.

### 1.2 `POST /api/v1/auth/login`  ·  **Opus**

**What.** Username and password in; sets the session cookie; returns the user,
**never a token**.

**Where.** New `app/api/auth.py`.

**Reuse, do not reimplement.** `auth.is_locked_out`, `auth.record_failure`,
`auth.clear_failures`, `auth.verify_password`, `auth.login_user` already back
the HTML login. A second password path that forgets the lockout is how
brute-force protection quietly stops applying.

- 401 on bad credentials, **429 when locked out** (15 minutes, `LOCKOUT_MINUTES`)
- Never reveal whether the username exists — the HTML form already gets this right
- `POST /api/v1/auth/logout` clears the session

**Verify.** Correct credentials set a cookie and a later `/me` succeeds with no
`Authorization` header; wrong password 401s; repeated failures 429; logout makes
the next call 401. Login and register are the only endpoints reachable
anonymously — extend the anonymous parametrisation to prove the rest still are
not.

### 1.3 SPA sign-in screen  ·  **Sonnet**

**What.** Username and password. Delete the token field, `getToken`, `setToken`
and `clearToken` — with a cookie there is nothing for the client to hold.

**Where.** `web/src/screens/SignIn.tsx`, `web/src/api/client.ts`,
`shared/api.ts`.

**`shared/api.ts` needs care — the native app imports it.** Add
`credentials: 'include'` and make `getToken` optional rather than required, so
the browser client passes no token and the native client still passes one. Both
must keep type-checking; `cd mobile && npx tsc --noEmit` is part of this task,
not an afterthought.

**Verify.** `web/e2e/auth.spec.ts`, rewritten: wrong password shows the error at
the form; correct credentials reach the list; the password field is
`type="password"`; **`localStorage` is empty afterwards except `theme`** — the
tracker's rule, asserted rather than assumed. Then `live.spec.ts` with real
credentials against the real stack.

### ⛔ Gate 1
Ship it. A reader signs in properly, nothing sensitive is in `localStorage`, and
everything below is additive.

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
| theme | **System / Light / Dark**, persisted, redraws the favicon |
| reader embeds | lazy Twitter/Instagram hydration |
| **command palette** | new — the tracker's, and the reason its shortcuts get used |
| **shortcuts overlay** | new — `?` lists them; betternews has five nobody can discover |

The last two are not parity items; they are the tracker's answer to the problem
that `j`/`k`/`l`/`o`/`r` exist today and nothing announces them. Port
`isEditableTarget` with them, or typing a search query starts firing shortcuts.
Theme gains **System**, which betternews lacks — a light/dark toggle cannot
follow the OS.

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

## Phase 7 — Settings  ·  **Opus** (shape) → **Sonnet** (screens)  ·  ✅ done (#41)

Landed as 14 endpoints, not 21: the four reader-behaviour panels (headlines,
padding, notifications, embeds) collapsed into one `GET/POST /settings/reader`,
since they are one screen's worth of toggles and the page-per-panel split in the
HTML UI was navigation for the server's benefit. The SPA renders all of them on
one scroll.

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
charts. **Recommendation: hand-rolled** — and the tracker settles it rather than leaving
it to taste: `react` and `react-dom` are its only dependencies, and 123 CSS
custom properties carry a design far more elaborate than six charts.

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

**~~The token lives in `localStorage`~~ — resolved.** The original plan accepted
a bearer token in `localStorage` and called it a reasonable trade for a LAN-only
reader. The tracker's rule is better and costs nothing: an `HttpOnly` cookie
cannot be read by injected script at all, and `SameSite=Strict` closes the
cross-site hole that made me choose bearer in the first place. The remaining
`localStorage` key is `theme`, which is the tracker's own sanctioned exception.

**The API now has two auth mechanisms.** Cookie for the browser, bearer for the
phone. That is a real cost — two paths to keep correct, and a test matrix that
has to cover both — but a native client cannot use cookies, so the alternative
is not one mechanism, it is a worse one. Every endpoint test should run under
both.

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

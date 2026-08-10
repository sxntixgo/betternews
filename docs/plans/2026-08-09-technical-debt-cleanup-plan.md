# Technical debt cleanup

## Goal

Delete what is no longer reachable, and fix the one place where dead code is
still *running*. Measured, not guessed: every item below was found by scanning
the tree, and each carries the evidence that says it is dead.

**Success criteria**

- No file in the repo is served, built, or imported without something using it.
- Neither stylesheet contains a rule for a class nothing renders.
- The full suite still passes on all three engines (`desktop`, `phone`,
  `safari`), and the backend keeps 100% coverage.
- Nothing here changes what a reader sees, with one exception that is called out
  and tested (Phase 1.4).

**Scope note.** The request was "debt we created during this". Most of what the
scan found is older — leftovers from the server-rendered UI deleted earlier. It
is listed anyway, marked by origin, because it is the same job and the same
risk. Phase 1.4 is not debt at all: it is a live bug the scan turned up, and it
is why Phase 1 goes first.

**Status: executed.** Phases 1, 2, 3.1 and 3.2 and 4 are done. Phase 3.3 was
decided: **keep both phone-sized projects.** Phase 2.1 took the second option
from the open questions — the surviving rules moved to a new `static/auth.css`
and `style.css` was deleted outright.

---

## Phase 1 — The dead PWA surface, and one live bug  ⛔ REVIEW GATE after 1.4

The server-rendered UI is gone, but its progressive-web-app assets are still in
the image and still served publicly.

### 1.1 Delete `static/sw.js` (147 lines)

A complete second service worker — cache-first article bodies, an offline vote
queue — for a UI that no longer exists.

**Evidence.** Nothing registers it. `templates/base.html` says so in a comment,
and the SPA registers its own at `/sw.js` (`web/src/pwa.ts:25`).

**Verify.** `curl -sk https://news.lan/static/sw.js` → 404 after deploy.

### 1.2 Delete `static/manifest.json` (511 bytes)

**Evidence.** `grep -rn "manifest.json" templates/ app/` returns nothing. The SPA
ships `web/public/manifest.webmanifest` with its own committed icons.

**Verify.** As above; `e2e/pwa.spec.ts` still passes.

### 1.3 Delete `create_icons.py` (29 lines) and its two Dockerfile lines

Generates placeholder PNGs into `static/` at build time (`Dockerfile:23`, `:26`).
Its output is named only by `static/manifest.json`, deleted in 1.2. The SPA's
icons are committed at `web/public/icon-192.png` / `icon-512.png`.

**Verify.** `docker compose build web` succeeds. (On the Windows box.)

### 1.4 Fix the unregister-all in `templates/base.html` — **this one is a bug**

`base.html` runs, on every render of `/login` and `/register`:

```js
navigator.serviceWorker.getRegistrations()
  .then(rs => rs.forEach(r => r.unregister()));
```

Its comment explains the intent: clear the *pre-cut-over* worker scoped to
`/static/`. But `getRegistrations()` returns **every** registration for the
origin, and Caddy serves Flask and the SPA from the same origin — so the SPA's
own service worker, the one fixed in #57, is unregistered every time anyone
visits the login page.

It is self-healing (the SPA re-registers on next load), which is why it went
unnoticed. What it costs is the offline shell on every sign-in, and it makes
service-worker behaviour on that origin nondeterministic — the class of thing
that made the iPhone failure so hard to pin down.

**Change it to scope the unregistration**, rather than deleting it: a browser
that visited before the cut-over may still hold the old worker.

```js
navigator.serviceWorker.getRegistrations().then(rs => rs.forEach(r => {
  // Only the pre-cut-over worker, which was scoped to /static/. Unregistering
  // everything also took out the SPA's own worker, on the same origin.
  if (r.active?.scriptURL.includes('/static/')) r.unregister();
}));
```

**Verify.** Register a worker, visit `/login`, assert the SPA's registration
survives. This cannot use the mocked projects (they never reach Flask) — it
belongs in `e2e/live.spec.ts`, the suite that exists for exactly this blind spot.

> **⛔ Gate.** Deploy Phase 1 alone. It touches the Docker image and a service
> worker, the two things that have already produced a blank page on a phone.
> Confirm the SPA loads and installs on the iPhone before starting Phase 2.

---

## Phase 2 — The old UI's stylesheet, which still exists twice

### 2.1 `static/style.css` — 990 lines, of which ~900 are a dead duplicate

This is the single largest piece of debt in the repo, and the answer to "did we
delete all the old Flask UI files" is **no — this one was missed**.

- **137 of its 150 classes** are rendered by no surviving template.
- **135 of those 137 are also defined in `web/src/App.css`.**

The entire old reading UI — `article-row`, `article-title`, `article-thumb`,
`article-summary`, `article-left`, `article-actions-inline`, the settings
panels, the insights histogram — exists in two stylesheets. One is live (the
SPA's). One is dead and still served at `/static/style.css`.

**What survives.** Thirteen classes, used by `login.html`, `register.html` and
`base.html`: `auth-card`, `hint`, `site-layout`, `site-layout-bare`,
`site-content`, `site-main`, `models-form`, `models-row`, `models-actions`,
`ollama-result`, `ollama-result-bad`, and two others.

**What to do.** Reduce `style.css` to those thirteen — roughly 990 lines to ~90.
Do not delete the file: `base.html` links it and the login page must render
without the SPA bundle.

**A naming note, not a task.** Those surviving names describe an Ollama models
panel, because the login form was styled by borrowing the settings CSS. Renaming
them to `auth-*` would be honest but touches three live templates for cosmetic
gain — worth doing only if you are in there anyway.

**Verify.** Load `/login` and `/register` signed out, at desktop and phone
width, light and dark. There is no automated coverage of these two pages'
*appearance*; `e2e/auth.spec.ts` exercises behaviour only. Screenshot before and
after and compare.

### 2.2 `web/src/App.css` — 56 dead classes, 26% of 215

The scan is deliberately conservative: it excludes any name that could be built
by a template literal, having found seven such prefixes in the code (`article`,
`card`, `diagnosis`, `embed`, `feed`, `prompt`, `tag`). That is why
`diagnosis-model_missing` is *not* listed — `App.tsx:549` composes it — while
`empty-model_missing` is, because nothing composes that one.

**Server-UI leftovers (47).** `action-model-form`, `action-suggestion-ok`,
`add-feed-form`, `aside-block`, `aside-body`, `aside-highlight`, `auth-card`,
`btn-read`, `btn-remove`, `btn-spinner`, `call-body`, `call-entry`,
`empty-model_missing`, `empty-ollama_unreachable`, `empty-state`, `hint`,
`hist-bar`, `hist-threshold`, `htmx-indicator`, `htmx-request`,
`insight-headline`, `load-more`, `modal-article-title`, `modal-description`,
`modal-nav-left`, `modal-nav-right`, `modal-title`, `models-actions`,
`models-form`, `models-row`, `models-saved`, `models-warn`, `ollama-result-ok`,
`opml-form`, `opml-status`, `prefs-form`, `prefs-meta`, `pull-indicator`,
`settings-group`, `sidebar-loading`, `site-layout-bare`, `site-main`,
`site-title`, `status-grid`, `status-panel`, `status-subhead`, `unread-count`

`htmx-indicator` and `htmx-request` are the clearest tell: htmx has not been in
this app for a long time.

**⚠ Check `aside-*` by eye, not by grep.** Article padding is a live feature. If
`Reader.tsx` renders folded blocks under different names these three are dead;
if the scan missed a dynamic name they are not.

**Orphaned by this week's work (8).** `digest-card`, `digest-link`,
`digest-meta`, `digest-refs` (#59, the digest became a modal); `sidebar-footer`,
`sidebar-tools`, `sidebar-username` (#63, the footer tray became sections);
`sidebar-nav` (dead well before either).

**Origin unclear (1).** `header-actions`.

**Verify.** Full e2e on all three engines. `design-system.spec.ts` already
asserts every `var(--token)` used is defined and that `App.css` holds no hex
literal and no literal radius; those guards must still pass. Then a visual pass
over the reader, settings, insights and the call log.

**Optional, and worth it.** Commit the scanner as `web/scripts/dead-css.mjs` so
this is a command rather than an afternoon. Do **not** wire it into CI: the
template-literal heuristic will eventually be wrong, and a false failure that
blocks a merge is worse than a quarterly manual run.

---

## Phase 3 — Test-suite debt

### 3.1 Delete `web/e2e/shot.spec.ts` (15 lines)

Its own docstring: *"Not an assertion — captures the phone layout for
eyeballing."* It runs on both phone-sized projects, waits a fixed 400 ms, writes
two gitignored PNGs, and asserts nothing — so it can only ever fail by timing
out.

### 3.2 Delete `test_htmx_request_to_login_is_not_redirected` (`tests/test_auth.py:278`)

It asserts that `GET /login` with an `HX-Request` header returns 200 and no
`HX-Redirect`. **No code in `app/` handles either header** — `grep -rn
"HX-Request\|HX-Redirect" app/` returns nothing. The test passes for a reason
unrelated to its name and pins behaviour nothing implements, for a client the
app no longer serves.

**Verify.** Backend coverage stays at 100% — if it drops, the test was covering
a real line and this analysis is wrong.

### 3.3 DECISION — `phone` and `safari` run identical metrics

Both use `devices['iPhone 13']`; only `browserName` differs. Every phone-sized
test runs twice, and the web CI job is ~4m20s.

**Not a recommendation to delete** — a question with a real trade-off, and it is
yours:

| option | keeps | loses | CI |
|---|---|---|---|
| **Keep both** | Chrome-on-Android *and* WebKit | — | ~4m20s |
| **Drop `phone`** | WebKit, which is what you read on | Android/Chromium at phone width | ~-30% |
| **Narrow `phone`** | both, cheaply | some duplicate coverage | between |

My inclination is **keep both**. WebKit found three real bugs in one afternoon
precisely because it was *different*; "two engines are redundant" is the
argument that produced the blind spot in the first place.

---

## Phase 4 — Documentation: mark, do not delete

Seven planning documents, ~1,300 lines describing finished or superseded work.
**They stay.** Each gets a status banner immediately under its title, so a
reader knows what they are holding before they act on it.

| file | banner |
|---|---|
| `improvements.md` | **✅ Completed.** Every item shipped. Superseded by `improvements-next.md`. |
| `improvements-next.md` | **✅ Completed.** All items shipped bar one, carried into `feature-plan.md`. |
| `plan.md` | **✅ Completed.** The original build plan. Its "REQUIRED SUB-SKILL" line names a `superpowers:` skill no longer in use — ignore it. |
| `refactor-plan.md` | **✅ Completed.** Presenter extraction shipped; `app/presenters.py` is guarded by `tests/test_presenters.py`. |
| `api-and-spa-plan.md` | **⚠️ Outdated — partly wrong.** §B.4 said settings, admin and insights would never be ported. That was **reversed**; the API now covers everything. See CLAUDE.md. |
| `plans/2026-08-01-spa-parity…` | **✅ Completed.** Delivered #50–#57. |
| `feature-plan.md` | **📌 Live.** Still cited by CLAUDE.md §0.3. No banner. |

`api-and-spa-plan.md` is the one that matters: it currently states as fact
something the codebase has since contradicted, which is a trap for anyone
reading it fresh. Marking it is the point of this phase.

**Verify.** Every file except `feature-plan.md` opens with a status line. No
file is removed; `git ls-files docs/` is unchanged.

---

## Risks

- **Phase 1 touches the Docker image and a service worker.** Both have produced
  a blank page on a phone before. Hence the gate, and hence deploying alone.
- **Phase 2.1 has no automated safety net.** Nothing tests how `/login` and
  `/register` *look*. Screenshot before and after.
- **The dead-CSS scan is a heuristic.** It cannot see a class assembled at
  runtime beyond the prefixes it detected. `aside-*` is the likeliest false
  positive.

## Out of scope (YAGNI)

- Restructuring `App.css` beyond deleting dead rules.
- Removing the four surviving Flask HTML routes. They are load-bearing: a
  browser with no session needs somewhere to land that does not depend on the
  SPA bundle, and the container healthcheck curls a URL.
- Deleting `static/style.css` or `templates/`. Both still render `/login` and
  `/register`.
- Renaming the login form's borrowed `models-*` class names.
- Consolidating the command palette against the new drawer sections. That
  duplication is deliberate — a palette entry is a shortcut, not a second UI.

## Open questions

1. **Phase 3.3** — keep both phone-sized projects, or drop `phone`?
2. **Phase 2.1** — reduce `style.css` in place, or split the thirteen surviving
   rules into a new `static/auth.css` and delete the old file outright? The
   second is cleaner and makes the deletion obvious in review; it costs one line
   in `base.html`.

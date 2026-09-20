# iPhone Reading UI Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task names the model that should implement it.

**Goal:** Fix seven defects a reader hit on an iPhone 16 Pro — a top bar that scrolls away, an empty Saved list, a hamburger sitting on top of the articles, switches rendering as circles, hidden-reasons surviving compact mode, an oversized headline, and a reader top bar that does not speak the app's design language.

**Architecture:** Six of the seven are front-end — `web/src/App.css` plus three components. One (Saved) is a backend read-path bug in `app/repo/articles.py`. Nothing here adds a dependency, a token, or a breakpoint. Tasks are ordered so the backend fix lands first (no CSS conflict) and the pixel-baseline regeneration lands last, once every visual change is in.

**Tech Stack:** React 19 + TypeScript + Vite (`web/`), Playwright (`web/e2e/`), Flask + SQLAlchemy Core + Postgres (`app/`), pytest (`tests/`).

**Spec:** This document. The defects were reported directly by the reader against the deployed stack on an iPhone 16 Pro (Safari / installed PWA); each task below records the root cause verified in the source rather than the symptom as reported.

---

## Global Constraints

Copied from `CLAUDE.md`; every task's requirements implicitly include these.

- **`App.css` contains no hex literal and no literal radius.** `e2e/design-system.spec.ts` asserts both, plus that every `var(--token)` used is actually defined. Use existing tokens from `web/src/index.css`; if a genuinely new colour is needed, define it in all **three** theme blocks (`:root`, `[data-theme=dark]`, and the `prefers-color-scheme` fallback) or it flashes the wrong colour on first paint.
- **Never edit a CSS selector list programmatically without stripping comments first.** Prefer dropping or adding whole rules to rewriting selectors. A cleanup whose diff is mostly reformatting hides the deletions it exists to show.
- **The whole desktop layout lives in one `@media (min-width: 900px)` block.** Below that it collapses to the phone layout, drawer overlay and all. Do not introduce a third breakpoint.
- **Every action needs a visible control**, not only a command-palette entry.
- **Hiding a control in the SPA is not gating an endpoint — do both.**
- **`npm run typecheck` covers both `src/` and `e2e/`.** Run it, not just the tests.
- **Do not drop `webkit` from the browser install.** `safari` is the only project running the engine the reader actually uses.
- **Regenerate a visual baseline only after a human has looked at the new image.** `toHaveScreenshot`'s default per-pixel threshold (0.2 YIQ) is above this palette's hairline contrast (~0.085), so a rule that moves or disappears does not register — verify low-contrast changes by measuring, not by watching the suite stay green.

### Current z-index ladder (`web/src/App.css`)

Task 2 changes this; every later task must respect the result.

| Layer | z-index | Before | After |
|---|---|---|---|
| `.app-header` | — | static (no stacking context) | **sticky, 15** |
| `.drawer-scrim` | 18 | fixed | unchanged |
| `.sidebar` (`@media max-width: 899px`) | 25 | fixed | unchanged |
| `.drawer-toggle` | 30 | **fixed**, `top: 58px; left: 24px` | **in flow inside `.app-header`, no z-index** |
| `.modal-backdrop` | 40 | fixed | unchanged |

### Commands

```bash
# backend
docker compose run --rm web pytest tests/ -q

# web, mocked (runs desktop + phone + safari)
cd web && npm run typecheck && npm run e2e

# one spec / one project
cd web && npx playwright test mobile.spec.ts --project=phone
cd web && npx playwright test visual.spec.ts --project=phone --update-snapshots

# production CSS minifier — typecheck and the dev-server e2e do not cover it
cd web && npm run build
```

---

## File Structure

| File | Responsibility | Touched by |
|---|---|---|
| `app/repo/articles.py` | All article SQL. `list_for_user` is the read path; `_visible` is where the dismissed split is decided. | Task 1 |
| `tests/test_api.py` | JSON API behaviour, including the Saved list. | Task 1 |
| `web/src/App.tsx` | The shell. Owns the filter state and decides when the dismissed pile is offered. | Task 1 |
| `web/src/App.css` | Every rule in this plan except the tokens. | Tasks 2–7 |
| `web/src/tags.ts` | **New.** The `tags` display preference, mirroring `photos.ts`. | Task 7 |
| `web/src/components/Drawer.tsx` | The drawer's display-preference block. | Task 7 |
| `web/src/components/Toolbar.tsx` | The single `.app-header`. | Task 2 (comment only) |
| `web/src/components/Reader.tsx` | The reader modal's top bar markup. | Task 6 |
| `web/src/App.tsx` | The shell: filter state (Task 1) and the `tags` preference (Task 7). | Tasks 1, 7 |
| `web/e2e/mobile.spec.ts` | Phone layout coverage. | Tasks 2, 3, 4, 5, 7 |
| `web/e2e/design-system.spec.ts` | Design-system invariants. | Task 6 |
| `web/e2e/visual.spec.ts-snapshots/` | 16 pixel baselines. | Task 7 |

---

## Task 1: The Saved list is empty

**Model: Opus.** It is a semantics change to a shared read path with a documented, deliberate filter on it. The fix has to be argued against the reason the filter exists, and it touches the same function three other lists page through.

### Root cause (verified)

`app/repo/articles.py:79` — `list_for_user` starts with `_visible(_card_select(user_id), dismissed)`, which for the default `dismissed=False` adds `WHERE user_article_state.dismissed_at IS NULL`. `dismiss_all` (line 208) dismisses **every** article matching the on-screen filter, and from the default list that filter does not exclude saved articles. So one press of *Mark all read* stamps `dismissed_at` on every saved article, and `GET /api/v1/articles?saved=1` returns nothing thereafter.

The drawer still shows a count, which is why this reads as "the list is broken" rather than "I dismissed them": `sidebar_counts` (line 348) counts `saved_at IS NOT NULL` with **no** dismissed condition — deliberately, because a save outlives a dismiss — so the drawer says `Saved articles 12` over an empty screen.

There is a second, narrower leak in the same function: line 82 restricts to `VISIBLE_STATUSES` (`summarized`) unless `hidden=True`, so an article saved from the Hidden list can never appear under Saved either.

The fix belongs on the read side, not in `dismiss_all`. Saving is an explicit keep; asking for the things you kept is not asking whether you have dealt with them — the same argument `search` already makes in its own comment two functions down.

**Files:**
- Modify: `app/repo/articles.py:79-96` (`list_for_user`)
- Modify: `web/src/App.tsx:133` (`offersDismissed`)
- Test: `tests/test_api.py` (append near `test_dismiss_all_respects_the_feed_and_saved_filters`, ~line 1893)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `list_for_user(db, user_id, *, saved=True, ...)` now returns saved articles regardless of `dismissed_at`, and regardless of whether their pipeline status is `summarized` or `hidden`. Signature is unchanged. No other task depends on this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def test_saved_survives_mark_all_read(client, app, token):
    """Saving is a keep, and Mark-all-read is not a question about keeps.

    `dismiss-all` stamps `dismissed_at` on everything the list showed, saved
    articles included, and the Saved list filtered on `dismissed_at IS NULL` --
    so one press emptied it. The drawer's count kept saying otherwise, because
    `sidebar_counts` never applied that filter, which is what made this read as
    breakage rather than as something the reader had done.
    """
    from app.db import get_db_direct
    from app.repo.articles import toggle_saved
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db, url="http://keep.example/f")
        aid = add_article(db, fid, seq=1, guid="k1", title="Worth keeping")
        add_article(db, fid, seq=2, guid="k2", title="Just read it")
        toggle_saved(db, ensure_bootstrap_user(db), aid)
        db.commit()
        db.close()

    assert client.post(f"{API}/articles/dismiss-all",
                       headers=auth(token)).get_json()["dismissed"] == 2

    saved = client.get(f"{API}/articles?saved=1", headers=auth(token)).get_json()
    assert [a["title"] for a in saved["articles"]] == ["Worth keeping"]
    # The drawer's count and the list must agree, in both directions.
    assert client.get(f"{API}/feeds", headers=auth(token)).get_json()["saved"] == 1
    # And the main list is still emptied -- this must not un-dismiss anything.
    assert client.get(f"{API}/articles", headers=auth(token)).get_json()["articles"] == []


def test_saved_includes_an_article_kept_from_the_hidden_list(client, app, token):
    """The Hidden list renders a Save button, so it has to mean something.

    `list_for_user` restricted every non-hidden query to status 'summarized',
    so an article saved out of Hidden was saved into a list that could not
    show it.
    """
    from app.db import get_db_direct
    from app.repo.articles import toggle_saved
    from app.repo.users import ensure_bootstrap_user
    with app.app_context():
        db = get_db_direct()
        fid = add_feed(db, url="http://hid.example/f")
        aid = add_article(db, fid, seq=1, guid="h1", title="Low score, kept anyway",
                          status="hidden")
        toggle_saved(db, ensure_bootstrap_user(db), aid)
        db.commit()
        db.close()

    saved = client.get(f"{API}/articles?saved=1", headers=auth(token)).get_json()
    assert [a["title"] for a in saved["articles"]] == ["Low score, kept anyway"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `docker compose run --rm web pytest tests/test_api.py -k "saved_survives or kept_from_the_hidden" -v`
Expected: both FAIL — `assert [] == ['Worth keeping']` and `assert [] == ['Low score, kept anyway']`.

- [ ] **Step 3: Make the read path treat a save as a keep**

In `app/repo/articles.py`, replace the opening of `list_for_user` (currently lines 79-92, from `stmt = _visible(...)` down to the `if saved:` block) with:

```python
def list_for_user(db, user_id: int, *, hidden: bool = False, saved: bool = False,
                  feed_id: int | None = None, sort: str = "date",
                  topic: str | None = None, limit: int = 50, offset: int = 0,
                  dismissed: bool = False):
    # Saved is the one list the dismissed split does not apply to, for the same
    # reason `search` below opts out of it: saving is an explicit keep, and
    # asking for the things you kept is not asking whether you have dealt with
    # them. `dismiss-all` stamps every article the current filter matched --
    # saved ones included -- so with the split on, one press of Mark all read
    # emptied this list while `sidebar_counts` (which has never applied the
    # split to `saved`) went on reporting a dozen of them.
    if not saved:
        stmt = _visible(_card_select(user_id), dismissed)
    else:
        stmt = _card_select(user_id)

    if saved and not hidden:
        # A Save button is rendered on the Hidden list, so it has to mean
        # something. Restricting to `summarized` here saved articles into a
        # list that could not show them.
        stmt = stmt.where(A.c.status.in_(VISIBLE_STATUSES + HIDDEN_STATUSES))
    else:
        stmt = stmt.where(
            A.c.status.in_(HIDDEN_STATUSES if hidden else VISIBLE_STATUSES))

    if topic:
        # An explicit topic filter is a deliberate request, so it overrides the
        # user's own hide stance for that topic.
        stmt = stmt.where(A.c.topics.any(topic))
    else:
        stmt = stmt.where(NOT_HIDDEN_SQL)
    if saved:
        # Something you saved is something you asked to keep.
        stmt = stmt.where(S.c.saved_at.isnot(None))
    if feed_id is not None:
        stmt = stmt.where(A.c.feed_id == feed_id)
```

Leave the rest of the function — `effective`, `cluster_expr`, `duplicates`, the `DISTINCT ON` collapse and the paging — exactly as it is.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm web pytest tests/test_api.py -k "saved_survives or kept_from_the_hidden" -v`
Expected: PASS.

- [ ] **Step 5: Run the whole backend suite**

Run: `docker compose run --rm web pytest tests/ -q`
Expected: PASS. Pay attention to `test_dismiss_all_respects_the_feed_and_saved_filters` and `test_the_dismissed_pile_is_its_own_paged_list` — neither asks for `saved=1`, so neither should move. If one does, the change leaked outside the `saved` branch.

- [ ] **Step 6: Stop offering the dismissed pile under Saved**

With the split off for Saved, `?saved=1` and `?saved=1&dismissed=1` would return overlapping sets and the pile would duplicate rows already on screen. `web/src/App.tsx:133`:

```tsx
  // Searching, the Hidden view and Saved are each their own answer to "what
  // should I look at"; a dismissed pile underneath them is noise. Saved is the
  // newest of the three and the strictest: it no longer applies the dismissed
  // split at all, so a pile under it would be the same rows a second time.
  const offersDismissed = !search && !hidden && !saved;
```

- [ ] **Step 7: Verify the web suite still passes**

Run: `cd web && npm run typecheck && npm run e2e`
Expected: PASS, all three projects.

- [ ] **Step 8: Commit**

```bash
git add app/repo/articles.py tests/test_api.py web/src/App.tsx
git commit -m "fix: Mark all read no longer empties the Saved list

Saving is an explicit keep, so the Saved list stops applying the dismissed
split -- and stops restricting to status 'summarized', which made a Save
button on the Hidden list mean nothing."
```

---

## Task 2: The top bar scrolls away, and the hamburger sits on the articles

**Model: Opus.** Two of the reported defects are one bug with one fix, and the fix reverses a decision `App.css` documents at length in a comment. Getting it wrong costs either a dead menu button or a header under the drawer, and it breaks a passing e2e test that must be re-aimed rather than deleted.

### Root cause (verified)

`App.css:31-36` says `.app-header` must not be positioned, because a `position` establishes a stacking context and `.drawer-toggle` inside it is `position: fixed` with `z-index: 30` specifically so it outranks the open drawer (`.sidebar`, z-index 25). That is a real constraint — and it is circular. The toggle is only fixed *because* the header cannot be; the header is only unpositioned *because* the toggle is fixed.

The two reported symptoms are the two halves of that circle:
- the header is not sticky, so *Mark all read* is unreachable from the bottom of a long list without scrolling all the way back up (**defect 1**);
- the toggle is `position: fixed; top: 58px; left: 24px` with no background of its own, so once the header scrolls past it, two ink-coloured bars float over the first headline (**defect 3**).

Break the circle at the toggle: put it back in the header's flow, make the header sticky, and let the **scrim** (z-index 18, already rendered and already wired to `setDrawerOpen(false)`) be what closes the drawer. The header then sits at z-index 15 — above the list, below the scrim and the drawer.

Two things fall out for free: the `52px` top padding exists only to clear the fixed toggle at `top: 58px`, so it drops to `14px` and the header gets shorter; and it can take `env(safe-area-inset-top)` via `max()`, which is inert today (no `viewport-fit=cover`, so iOS already insets the web view and `env()` resolves to 0) and correct the day that changes.

**Files:**
- Modify: `web/src/App.css:31-36` (the "Not sticky" comment), `:233-246` (`.drawer-toggle`), `:247-252` (`.drawer-toggle span`), `:262-266` (the `max-width: 899px` block's toggle rules), `:1187-1199` (`.app-header`)
- Modify: `web/src/components/Toolbar.tsx:88-97` (the toggle's comment)
- Modify: `web/e2e/mobile.spec.ts:470-475`
- Test: `web/e2e/mobile.spec.ts` (new tests in the `the top bar and the drawer fit the screen` describe block)

**Interfaces:**
- Consumes: nothing.
- Produces: `.app-header` is `position: sticky; top: 0; z-index: 15`. `.drawer-toggle` is in flow, no `position`, no `z-index`. **Task 6 must not give the reader modal a z-index below 15**, and Task 3's tap-target work must not re-introduce a `min-height` that changes the header's height.

- [ ] **Step 1: Write the failing tests**

Add to `web/e2e/mobile.spec.ts`, inside the existing `test.describe('the top bar and the drawer fit the screen', ...)` block:

```ts
  test('the top bar stays on screen at the bottom of the list', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // Mark all read is a header action, and the reader reaches for it after
    // reading the last story on screen -- which is exactly where an unpinned
    // header is furthest away. It was not sticky because the hamburger inside
    // it was `position: fixed` to outrank the open drawer; the scrim closes
    // the drawer now, so the header can pin and the hamburger can ride with it.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const header = page.locator('.app-header');
    await expect(header).toBeInViewport();
    expect((await header.boundingBox())!.y).toBeLessThanOrEqual(1);
    await expect(header.getByRole('button', { name: 'Mark all read' })).toBeInViewport();
  });

  test('the menu button never sits on top of a headline', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // It was fixed at top:58px/left:24px with no background, so once the
    // header scrolled past, two ink bars floated over the first story's
    // headline. In the header's flow it cannot overlap anything below it.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const toggle = (await page.locator('.drawer-toggle').boundingBox())!;
    const header = (await page.locator('.app-header').boundingBox())!;
    expect(toggle.y + toggle.height, 'the toggle escaped the header')
      .toBeLessThanOrEqual(header.y + header.height + 1);

    // And the element under the first headline's top-left corner is the
    // headline, not the button.
    const title = (await page.locator('.article-title').first().boundingBox())!;
    const onTop = await page.evaluate(
      ([x, y]) => (document.elementFromPoint(x, y) as HTMLElement)?.className ?? '',
      [title.x + 4, title.y + 4] as const,
    );
    expect(onTop).not.toContain('drawer-toggle');
  });

  test('the drawer covers the header, and the scrim closes it', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The header is sticky now, so it has a stacking context: it must sit
    // *under* the scrim (18) and the drawer (25), and the scrim -- not the
    // hamburger buried beneath it -- is what shuts the drawer again.
    await openDrawer(page);
    await expect(page.locator('.sidebar.open')).toHaveCount(1);
    await page.locator('.drawer-scrim').click({ position: { x: 340, y: 40 } });
    await expect(page.locator('.sidebar.open')).toHaveCount(0);
  });
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone -g "stays on screen|on top of a headline|covers the header"`
Expected: the first two FAIL (the header's `y` goes negative as the page scrolls; the toggle is fixed and outlives the header). The third may already pass — the scrim is wired up today — and that is fine; it is there to keep the closing path from regressing.

- [ ] **Step 3: Replace the "Not sticky" comment**

`web/src/App.css:31-36` — the comment now states the opposite of what the file does, and a stale comment here is what kept this bug alive. Replace it with:

```css
/* `.app-header` is sticky (see its rule below). It could not be while
   `.drawer-toggle` was `position: fixed` to outrank the open drawer: a sticky
   ancestor establishes a stacking context, so no z-index on the toggle could
   have out-ranked a sibling context at all. That was circular -- the toggle
   was fixed because the header could not pin, and the header could not pin
   because the toggle was fixed -- and it cost both of the things this pair
   was arranged to protect: Mark all read was unreachable from the bottom of a
   long list, and the fixed toggle floated over the first headline with no
   background of its own. The drawer's scrim closes the drawer now, so the
   toggle rides in the header's flow and the header pins.

   The missed strip below stays unpinned: it scrolls with the list. */
```

- [ ] **Step 4: Put the toggle back in the header's flow**

Replace `.drawer-toggle` and `.drawer-toggle span` (`App.css:224-252`) with:

```css
/* Mobile drawer. Two bars, in the header's flow -- not fixed. It was fixed so
   it could sit above the open drawer (z-index 25) from inside a header that
   had no stacking context of its own; that is what put it on top of the first
   headline whenever the header scrolled away. The drawer covers it now, and
   `.drawer-scrim` is what closes it. */
.drawer-toggle {
  display: none;
  /* 40x40 taken here rather than inherited from the coarse-pointer
     `min-height`, which only sets one axis and would leave an 18px-wide
     target. The bars stay 18px; the button around them is the tap area. */
  width: 40px;
  height: 40px;
  flex: none;
  /* The bars line up with the title text's left edge; the target overhangs
     into the gutter, which is dead space anyway. */
  margin-left: -10px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  background: none;
  border: 0;
  padding: 0;
  cursor: pointer;
}
.drawer-toggle span {
  display: block;
  /* Explicit now: the button used to be exactly 18px wide and the bars simply
     filled it. */
  width: 18px;
  height: 1.5px;
  background: var(--color-ink);
}
```

- [ ] **Step 5: Drop the space the fixed toggle used to need**

In the `@media (max-width: 899px)` block (`App.css:261-266`), delete the `.header-title` reservation — the toggle is a flex item in that row now and takes its own width:

```css
@media (max-width: 899px) {
  .drawer-toggle { display: flex; }
  .sidebar {
```

(That is: remove the two comment lines and the `.header-title { padding-left: 32px; }` rule, and nothing else from the block.)

- [ ] **Step 6: Pin the header**

Replace the `.app-header` rule (`App.css:1187-1199`) with:

```css
.app-header {
  /* Pinned, so Mark all read is reachable from the bottom of a long list
     rather than only from the top of it. */
  position: sticky;
  top: 0;
  /* Above the list, below `.drawer-scrim` (18) and `.sidebar` (25): the drawer
     is meant to cover this, and the scrim is what closes it. Well below
     `.modal-backdrop` (40). */
  z-index: 15;
  /* The hairline lives here, not on a wrapper. `.site-header` was a <header>
     nested inside this one whose only remaining job was to draw this line --
     and it drew it across the whole window while the column beneath it is
     capped at 760px, so the rule ran past every card it was meant to close
     off. On this element it ends where the reading measure does. */
  border-bottom: 1px solid var(--color-hairline);
  /* Opaque, and now load-bearing rather than cosmetic: the list scrolls under
     this. */
  background: var(--color-bg);
  display: flex;
  flex-direction: column;
  gap: 18px;
  /* Was 52px on top, which was clearance for a hamburger fixed at top:58px and
     nothing else. `max()` with the inset is inert today -- there is no
     `viewport-fit=cover`, so iOS insets the web view itself and `env()`
     resolves to 0 -- and is correct the day that changes. */
  padding: max(14px, env(safe-area-inset-top)) 24px 16px;
}
```

- [ ] **Step 7: Correct the toggle's comment in the component**

`web/src/components/Toolbar.tsx:88-97` — the JSX comment still explains the fixed positioning. Replace the paragraph beginning "`.drawer-toggle` survives for the same reason" with:

```
          `.drawer-toggle` keeps its class for the same reason -- it is the
          control other specs open the drawer by. It is no longer fixed over
          the list: it is a flex item in this row, the header is sticky, and
          the scrim is what closes the drawer once it is open.
```

- [ ] **Step 8: Re-aim the one test that closed the drawer with the toggle**

`web/e2e/mobile.spec.ts:470-475`, inside `it takes the reader lead image with it`. The toggle is under the drawer now, so clicking it is a click on the scrim in disguise. Make that explicit:

```ts
    // Shut the drawer: on a phone it covers the list, and Escape does not close
    // it -- it is not a dialog. The scrim, not the hamburger: the toggle rides
    // in the sticky header now and the open drawer covers it.
    // The position matters: the scrim is `inset: 0`, so its own (5,5) lies
    // under the 260px drawer and Playwright reports the click intercepted.
    // Anything right of 260px hits scrim that is actually exposed.
    await page.locator('.drawer-scrim').click({ position: { x: 340, y: 40 } });
    await expect(page.locator('.sidebar.open')).toHaveCount(0);
```

- [ ] **Step 9: Run the new tests**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone --project=safari`
Expected: PASS, including `the compact header stays compact` (`header.height < 130` — the header is now ~70px, down from ~120px).

- [ ] **Step 10: Run the full web suite**

Run: `cd web && npm run typecheck && npm run e2e`
Expected: PASS except `visual.spec.ts`, whose `list-*` and `drawer-*` baselines now differ by a shorter header. **Do not regenerate them here** — Task 7 does it once, after every visual change is in. Note which snapshots failed and carry the list forward.

- [ ] **Step 11: Commit**

```bash
git add web/src/App.css web/src/components/Toolbar.tsx web/e2e/mobile.spec.ts
git commit -m "fix: pin the top bar and take the hamburger off the articles

The toggle was fixed so it could outrank the open drawer, which is why the
header could not be sticky, which is why the toggle floated over the first
headline. The scrim closes the drawer now; both halves go away."
```

---

## Task 3: The Photos and Compact switches render as circles

**Model: Sonnet.** A narrow, fully diagnosed CSS bug, but the obvious fix (drop the tap-target floor) trades an accessibility guarantee for a shape. The implementer has to keep both.

### Root cause (verified)

`App.css:577-590`:

```css
@media (pointer: coarse) {
  button:not(.pill), .btn-icon, .btn-external, .sidebar-feed, .sidebar-collapse, .sidebar-manage {
    min-height: 40px;
  }
```

`.toggle` is a `<button role="switch">` without `.pill`, so on any touch device it becomes `42px × 40px` with `border-radius: var(--radius-pill)` (999px) — a circle. The rule is invisible on a desktop, which is why this survived: the drawn size (`42 × 26`) only applies to a fine pointer.

`.segment` is caught by the same rule: the Sort and Theme radiogroups' options stand 40px tall inside a `padding: 3px` track, which is why that block reads as much heavier on a phone than in the design.

The floor itself is right and stays. The switch gives its tap area back with a pseudo-element instead of by growing — the same technique `.action` already uses on the card ("padding plus a negative margin rather than by growing", per `mobile.spec.ts:43`).

**Files:**
- Modify: `web/src/App.css:359-368` (`.toggle`, `.toggle-knob`), `:577-590` (the coarse-pointer block)
- Test: `web/e2e/mobile.spec.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `.toggle` measures `42 × 26` at every pointer type and carries a `44 × 50` hit area via `::after`. No class or accessible name changes — `getByRole('switch', { name: 'Show photos' | 'Compact list' })` keeps working, and roughly ten tests depend on that.

- [ ] **Step 1: Write the failing test**

Add to `web/e2e/mobile.spec.ts`, in the `the top bar and the drawer fit the screen` describe block:

```ts
  test('the switches are pills, and still clear the tap floor', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // `@media (pointer: coarse)` put a 40px floor on every button without
    // `.pill`. A switch is a track: 42 wide, floored to 40 tall, with a 999px
    // radius, it rendered as a circle on every phone -- and only on a phone,
    // which is why it lived this long. The drawn size comes back and the tap
    // target moves to a pseudo-element.
    await openDrawer(page);
    const toggle = page.getByRole('switch', { name: 'Compact list' });
    const box = (await toggle.boundingBox())!;
    expect(box.height, 'the track grew to meet the tap floor').toBeLessThanOrEqual(28);
    expect(box.width / box.height, 'a switch is wider than it is tall')
      .toBeGreaterThan(1.4);

    // The target is still there, it is just not the painted box.
    const hit = await toggle.evaluate((el) => {
      const r = getComputedStyle(el, '::after');
      const b = el.getBoundingClientRect();
      const grow = (v: string) => Math.abs(parseFloat(v) || 0);
      return {
        w: b.width + grow(r.left) + grow(r.right),
        h: b.height + grow(r.top) + grow(r.bottom),
      };
    });
    expect(Math.min(hit.w, hit.h)).toBeGreaterThanOrEqual(44);
  });

  test('the segmented controls do not stand 40px tall', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // Same floor, same shape problem, one step smaller: Sort and Theme are
    // two- and three-position radiogroups, not primary actions.
    await openDrawer(page);
    const segment = page.getByRole('radiogroup', { name: 'Sort' })
      .getByRole('radio').first();
    const box = (await segment.boundingBox())!;
    expect(box.height).toBeLessThanOrEqual(34);
    // WCAG 2.5.8 is 24px; this must stay above it.
    expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(24);
  });
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone -g "switches are pills|do not stand 40px"`
Expected: both FAIL — height 40, ratio 1.05.

- [ ] **Step 3: Give the switch its hit area without growing it**

Replace `.toggle` and add the pseudo-element (`App.css:359-368`):

```css
.toggle {
  width: 42px; height: 26px; flex: none;
  border: 0; padding: 0 3px;
  border-radius: var(--radius-pill);
  background: var(--color-toggle-off);
  display: flex; align-items: center; cursor: pointer;
  /* Anchor for the hit area below. */
  position: relative;
}
/* The tap target, separated from the drawn control. A switch is a track, and
   a track grown to a 40px floor under `--radius-pill` is a circle -- which is
   what these looked like on a phone. Absolutely positioned, so it is not a
   flex item of the track above it. 42+8 x 26+18 = 50x44. */
.toggle::after {
  content: '';
  position: absolute;
  inset: -9px -4px;
}
.toggle[aria-checked='true'] { background: var(--color-accent); justify-content: flex-end; }
.toggle-knob { width: 20px; height: 20px; border-radius: var(--radius-pill); background: var(--color-segment-selected); }
```

- [ ] **Step 4: Exempt the two shaped controls from the floor**

Append inside the existing `@media (pointer: coarse)` block (`App.css:577-590`), after the `.btn-icon, .sidebar-collapse, .sidebar-manage` line — add rules, do not rewrite the selector list above them:

```css
  /* Two controls whose shape *is* their meaning, and for which a height floor
     is the wrong instrument. `.toggle` takes its 44px target from `::after`
     instead; `.segment` sits in a 3px track, so a 40px floor makes the whole
     radiogroup 46px tall. 32 clears WCAG 2.5.8's 24px with room over. */
  button.toggle { min-height: 0; }
  button.segment { min-height: 32px; }

  /* Qualified with the element on purpose: the floor's selector is
     `button:not(.pill)` = (0,1,1), which outranks a bare `.toggle` = (0,1,0)
     wherever it sits in the file. `button.toggle` matches that specificity, so
     the later position wins. A bare class measures 40px and looks like it
     worked. */
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone --project=safari -g "switches are pills|do not stand 40px"`
Expected: PASS on both projects.

- [ ] **Step 6: Verify nothing else measured the switch**

Run: `cd web && npm run e2e`
Expected: PASS except the known `visual.spec.ts` drift. `design-system.spec.ts:343,381` and every `mobile.spec.ts` density/photos test address the switches by role and name, not by size, so they must not move.

- [ ] **Step 7: Commit**

```bash
git add web/src/App.css web/e2e/mobile.spec.ts
git commit -m "fix: the drawer switches are pills on a phone again

The coarse-pointer 40px floor applied to every button without .pill, which
made a 42x26 track 42x40 under a 999px radius -- a circle, and only ever on
a touch device. The target moves to ::after; segments get a smaller floor."
```

---

## Task 4: The hidden-reason survives compact mode

**Model: Haiku.** One CSS declaration and one assertion. The cause is unambiguous and there is no design judgment left to make.

### Root cause (verified)

`ArticleCard.tsx:98-100` renders the reason as its own paragraph:

```tsx
{article.hidden && article.score_reason && (
  <p className="hidden-reason">Hidden: {article.score_reason}</p>
)}
```

`App.css:1131` hides only the summary in compact mode:

```css
[data-density='compact'] .article-summary { display: none; }
```

So in the Hidden list, compact drops the summary and leaves a second paragraph of italic prose in its place — which is most of what compact was meant to reclaim. The reason is not lost: it is still the `title` attribute on `.meta-score` (`ArticleCard.tsx:106`).

**Files:**
- Modify: `web/src/App.css:1128-1132`
- Test: `web/e2e/mobile.spec.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks use.

- [ ] **Step 1: Write the failing test**

Add to `web/e2e/mobile.spec.ts`, in the same describe block as `compact mode trades summaries for stories on screen`:

```ts
  test('compact mode drops the hidden-reason with the summary', async ({ page }) => {
    // Compact hid `.article-summary` and nothing else, so on the Hidden list it
    // traded one paragraph of prose for another -- the reason is longer than
    // some summaries. It is still on the score's `title` attribute, so nothing
    // is lost by dropping it from the row.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [article(1, {
        hidden: true,
        score_reason: 'No stated interest in municipal parking policy.',
      })],
      next_offset: null, diagnosis: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await expect(page.locator('.hidden-reason')).toBeVisible();

    await openDrawer(page);
    await page.getByRole('switch', { name: 'Compact list' }).click();
    await expect(page.locator('.hidden-reason')).toBeHidden();
    // Still reachable, just not as a second paragraph.
    await expect(page.locator('.meta-score').first())
      .toHaveAttribute('title', 'No stated interest in municipal parking policy.');
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone -g "drops the hidden-reason"`
Expected: FAIL at `expect(locator).toBeHidden()` — the paragraph is still visible.

- [ ] **Step 3: Hide it with the summary**

Replace `App.css:1128-1132` with:

```css
/* Compact list. The summary was the whole saving, and the reason a hidden
   article was hidden has to go with it: on the Hidden list it is a second
   paragraph of prose, often longer than the summary compact just dropped. It
   is still the `title` on `.meta-score`, so nothing is lost. The tags and the
   kind that compact also used to hide have gone from the card entirely, and
   the meta line is one line in either mode. */
[data-density='compact'] .article-summary,
[data-density='compact'] .hidden-reason { display: none; }
[data-density='compact'] .article-row { padding: 6px 0; }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone --project=safari -g "drops the hidden-reason"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/App.css web/e2e/mobile.spec.ts
git commit -m "fix: compact mode drops the hidden-reason too"
```

---

## Task 5: The headline is too large in the list

**Model: Haiku.** Two numeric values with the reasoning supplied. The only judgment — how far down — is made below, and the existing tests draw the floor.

### Root cause (verified)

`App.css:455-463` — `.article-title` is `19px / 1.32 / 600 / -0.35px` at phone width and `20px / 1.3` above 900px. On a 390pt iPhone that is close to the reader's body text and, at three or four lines a headline, sets the height of every card.

Target: **17px**, line-height **1.35**, letter-spacing **-0.2px**. Tighter tracking hurts more as size falls, so the negative tracking relaxes as the size drops rather than staying put. The desktop value is not changed: the measure is 760px there and 20px is right for it.

Existing tests set the floor, and both should improve rather than break:
- `mobile.spec.ts:60` — `title.width / viewport > 0.4` (a width claim, unaffected by size).
- `mobile.spec.ts:165` — compact fits `> 4.5` stories per screen and saves `> 30px` against comfortable. The summary is still the saving; the delta does not move, and both heights come down.

**Files:**
- Modify: `web/src/App.css:455-463`
- Test: `web/e2e/mobile.spec.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks use. Changes the `list-*` visual baselines (Task 7).

- [ ] **Step 1: Write the failing test**

Add to `web/e2e/mobile.spec.ts`, in the `the top bar and the drawer fit the screen` describe block:

```ts
  test('the headline is a headline, not a heading', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // 19px on a 390pt screen sat a headline within a point of the body text
    // and, at three lines, set the height of every card. 17 keeps the weight
    // and the hierarchy against the 14px summary and buys back a story a
    // screen. The desktop keeps 20 -- it has a 760px measure to fill.
    const title = page.locator('.article-title').first();
    await expect(title).toHaveCSS('font-size', '17px');
    const summary = page.locator('.article-summary').first();
    const [t, s] = [
      parseFloat(await title.evaluate((el) => getComputedStyle(el).fontSize)),
      parseFloat(await summary.evaluate((el) => getComputedStyle(el).fontSize)),
    ];
    expect(t, 'the headline must still outrank the summary').toBeGreaterThan(s + 2);
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone -g "is a headline, not a heading"`
Expected: FAIL — `Expected: "17px" Received: "19px"`.

- [ ] **Step 3: Bring the size down**

Replace `.article-title` (`App.css:455-463`) with:

```css
.article-title {
  /* 17, from 19. At 19 a headline on a 390pt screen sat within a couple of
     points of the body text while setting the height of every card; the
     hierarchy against the 14px summary is what carries it, not the size.
     The desktop override below keeps 20 -- it has a 760px measure to fill.
     Tracking relaxes with the size: -0.35px is a display-size correction and
     reads as cramped at 17. */
  font-size: 17px;
  line-height: 1.35;
  font-weight: 600;
  letter-spacing: -0.2px;
  color: var(--color-ink);
  text-wrap: pretty;
  cursor: pointer;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone --project=safari -g "is a headline, not a heading"`
Expected: PASS.

- [ ] **Step 5: Verify the density and width claims still hold**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone -g "compact mode trades|gets most of the width|the headline sits beside the photo"`
Expected: PASS. If `compact ... toBeLessThan(comfortable - 30)` fails, the summary is no longer the dominant saving at this size — report it rather than loosening the threshold.

- [ ] **Step 6: Commit**

```bash
git add web/src/App.css web/e2e/mobile.spec.ts
git commit -m "fix: 17px headlines in the reading list

19 put a headline within a couple of points of the body text on a phone and
set the height of every card. Desktop keeps 20."
```

---

## Task 6: The reader's top bar does not speak the app's language

**Model: Sonnet.** The fix is small but it is a design judgment — deciding what "matches the system" means here, and which of the two existing vocabularies wins — and it removes CSS that other screens still use the classes of. That needs more care than a mechanical edit.

### Root cause (verified)

The app has one header vocabulary, set by `.app-header`: plain text actions (`.header-action`, 13px, `--color-ink-muted`, no border, no glyph), a hairline rule beneath, `--color-bg` behind. `CLAUDE.md` states the rule as "Actions are words, not emoji."

The reader's top bar (`Reader.tsx:38-47`, `App.css:669-680`) is from before that: `← Back` as a `.btn-icon` (bordered, radius-sm, hover-fills its background) and `↗ Open in browser` as a `.btn-external` (a bordered box), on a bar with 12px/20px padding — and then overridden again at ≤899px to 32px and 13px so they "don't dominate the screen". Three different sets of metrics for one row.

The fix is to speak `.app-header`'s language: the same 13px text actions, the same hairline, the same ground, the same `max(…, env(safe-area-inset-top))` treatment Task 2 gave the main header. The side padding stays at the **modal's** 20px rather than the header's 24/48, because the modal is its own surface and `.modal-body` sets the measure the nav has to align to — the type is what makes it read as one system, not the gutter.

`.btn-icon` and `.btn-external` stay in the stylesheet: nine other screens use them. This task only stops the reader from using them.

Two dead rules go with it: the `dialog#reader-modal` override at `App.css:282-289` and the `.modal-nav .btn-icon / .btn-external` override at `:293-298`. The reader has not been a native `<dialog>` since `components/Modal.tsx` replaced it — nothing in `src/` renders one (`grep -rn "<dialog" web/src` returns only a comment).

**Files:**
- Modify: `web/src/components/Reader.tsx:38-47`
- Modify: `web/src/App.css:282-298` (delete two dead overrides), `:669-680` (`.modal-nav`)
- Test: `web/e2e/design-system.spec.ts`

**Interfaces:**
- Consumes: Task 2's ladder — the reader sits inside `.modal-backdrop` at z-index 40, comfortably above the sticky header's 15. Nothing to change.
- Produces: `.modal-nav` is a `.app-header`-shaped bar; its two controls carry `.header-action`. No accessible names change: "Back" and "Open in browser" keep their exact text.

- [ ] **Step 1: Write the failing test**

Add to `web/e2e/design-system.spec.ts`:

```ts
test('the reader top bar speaks the app header language', async ({ page }) => {
  // There is one header vocabulary -- `.header-action`: 13px text, ink-muted,
  // no border, no glyph, a hairline under the row. The reader's bar predated
  // it and carried `.btn-icon` / `.btn-external` (bordered boxes with arrow
  // glyphs) plus a third set of metrics under 899px, so the one screen a
  // reader spends the most time on looked like a different application.
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
  await page.locator('.article-title').first().click();

  const nav = page.getByRole('dialog').locator('.modal-nav');
  await expect(nav).toBeVisible();
  // Same classes as the list header's actions, and only those.
  await expect(nav.locator('.btn-icon, .btn-external')).toHaveCount(0);
  await expect(nav.getByRole('button', { name: 'Back' })).toHaveClass(/header-action/);
  await expect(nav.getByRole('link', { name: 'Open in browser' }))
    .toHaveClass(/header-action/);
  // Words, not glyphs.
  await expect(nav).not.toContainText('←');
  await expect(nav).not.toContainText('↗');
  // Same type and the same hairline as `.app-header`.
  const listHeader = page.locator('.app-header');
  const rule = await listHeader.evaluate((el) => getComputedStyle(el).borderBottomColor);
  await expect(nav).toHaveCSS('border-bottom-color', rule);
  await expect(nav.getByRole('button', { name: 'Back' })).toHaveCSS('font-size', '13px');
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx playwright test design-system.spec.ts --project=phone -g "reader top bar speaks"`
Expected: FAIL at `toHaveCount(0)` — the bar still holds a `.btn-icon` and a `.btn-external`.

- [ ] **Step 3: Restyle the reader's nav markup**

`web/src/components/Reader.tsx`, replace the `<nav>` block:

```tsx
      {/* The same vocabulary as `.app-header`: text actions, no borders, no
          glyphs. It carried `.btn-icon` and `.btn-external` from before that
          header existed, which made the one screen a reader spends the most
          time on look like a different application. Those classes stay in the
          stylesheet -- nine other screens use them -- this bar just stops
          being one of them. */}
      <nav className="modal-nav">
        <button className="header-action is-ink" onClick={onClose}>
          Back
        </button>
        {detail && (
          <a
            className="header-action"
            href={detail.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open in browser
          </a>
        )}
      </nav>
```

- [ ] **Step 4: Give the bar the header's metrics**

Replace `.modal-nav` (`App.css:669-680`) with:

```css
/* Shaped like `.app-header`, and for the same reasons -- one hairline, the
   page ground behind it, actions as 13px text. The side padding is the
   modal's 20px rather than the header's 24, because this bar aligns to
   `.modal-body` beneath it; it is the type that makes the two read as one
   system, not the gutter. The top inset matches the list header's treatment
   and is inert until there is a `viewport-fit=cover` to make it real. */
.modal-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: max(14px, env(safe-area-inset-top)) 20px 14px;
  border-bottom: 1px solid var(--color-hairline);
  background: var(--color-bg);
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 1;
}
/* `.header-action` is a <button> rule; the Open link needs the same box. */
.modal-nav .header-action { text-decoration: none; }
```

- [ ] **Step 5: Delete the two rules that are now dead**

In the `@media (max-width: 899px)` block, remove the `dialog#reader-modal { … }` rule (`App.css:282-289`, together with its "Reader modal goes full-bleed" comment) and the `.modal-nav { padding: 6px 12px; }` line plus the `.modal-nav .btn-icon, .modal-nav .btn-external { … }` rule and its comment (`:290-298`). Drop whole rules — do not rewrite the selector lists around them.

Verify nothing else wanted them:

```bash
cd web && grep -rn "reader-modal" src/ e2e/          # expect: no matches
cd web && grep -rn "btn-icon\|btn-external" src/     # expect: matches only outside Reader.tsx
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd web && npx playwright test design-system.spec.ts --project=phone --project=desktop --project=safari -g "reader top bar speaks"`
Expected: PASS on all three.

- [ ] **Step 7: Run the reading and design suites**

Run: `cd web && npm run typecheck && npx playwright test reading.spec.ts design-system.spec.ts redesign.spec.ts`
Expected: PASS. `design-system.spec.ts` asserts `App.css` holds no hex literal and no literal radius and that every `var(--token)` resolves — the rules above use tokens only.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/Reader.tsx web/src/App.css web/e2e/design-system.spec.ts
git commit -m "fix: the reader top bar uses the app header vocabulary

Text actions, one hairline, the page ground -- instead of two bordered
button styles with arrow glyphs and a third set of metrics under 899px.
Takes two dead <dialog>-era overrides with it."
```

---

## Task 7: A Tags switch in the drawer

**Model: Sonnet.** It is a new preference rather than a bug fix — a new module, three components and a stylesheet rule, following a pattern `photos.ts` and `density.ts` already set. The one judgment is what the switch does at phone width, and that is settled below.

### What this adds, and the decision behind it

A fourth per-device display preference, `tags`, beside `theme`, `density` and `photos`, rendered as a `Toggle` in `.drawer-settings`.

The card already renders one topic (`ArticleCard.tsx:129-142`), but `.meta-tag` is `display: none` at base and turns on only inside the `@media (min-width: 900px)` block (`App.css:1147,1158,1368`) — the meta line is a single line on a phone and the tag is the item that would wrap it. So on the device that asked for this switch there is currently nothing for it to hide.

**The preference replaces the breakpoint, and defaults to `off`.** The switch then means the same thing on both devices: off is what a phone shows today, and turning it on shows tags wherever you are. The cost is that a desktop loses its single tag until the reader flips the switch once — acceptable, because these preferences are per-device localStorage and a desktop reader sets theirs once anyway. The alternative, defaulting on, would put a tag on every card on the phone without anyone asking for it.

The phone's one-line meta rule is protected by bringing back the **13ch cap** the redesign removed. That cap was dropped along with the tag row that needed it; the tag is back at phone width now, so the cap comes back with it. `mobile.spec.ts:217` asserts that line stays under 48px, which is the test that would catch a wrap.

**Files:**
- Create: `web/src/tags.ts`
- Modify: `web/src/App.tsx` (state, effect, `Drawer` prop, palette entry), `web/src/components/Drawer.tsx` (prop + `Toggle`), `web/src/App.css:1143-1158` and `:1368`
- Test: `web/e2e/mobile.spec.ts`

**Interfaces:**
- Consumes: nothing from Tasks 1-6.
- Produces: `loadTags(): Tags`, `setTags(v: Tags): void`, `applyTags(v: Tags): void` with `type Tags = 'on' | 'off'`, exactly mirroring `web/src/photos.ts`. `<html data-tags>` is stamped. `Drawer` gains two required props, `tags: Tags` and `setTagsState: Dispatch<SetStateAction<Tags>>` — required, not optional, because "a prop made optional just to quiet the compiler is how a control comes out of a refactor still rendering and doing nothing" (`CLAUDE.md`). Task 8 rebuilds the `drawer-*` baselines this changes.

- [ ] **Step 1: Write the failing tests**

Add to `web/e2e/mobile.spec.ts`, in the `the top bar and the drawer fit the screen` describe block:

```ts
  test('the tags switch shows and hides the topic, on a phone too', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The tag was desktop-only: `display: none` at base, `inline` inside the
    // 900px block, because the meta line is one line on a phone and the tag is
    // the item that wraps it. The preference replaces that breakpoint, so the
    // switch means the same thing on both devices -- and defaults off, which
    // is what a phone shows today.
    await expect(page.locator('.meta-tag').first()).toBeHidden();

    await openDrawer(page);
    const tags = page.getByRole('switch', { name: 'Show tags' });
    await expect(tags).toHaveAttribute('aria-checked', 'false');
    await tags.click();
    await page.locator('.drawer-scrim').click({ position: { x: 340, y: 40 } });

    await expect(page.locator('.meta-tag').first()).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-tags', 'on');
    // And it must not cost the single meta line. 48, the same floor the
    // source-and-age test uses: the actions stand 40px tall, so anything
    // under 48 is one line and only a wrap clears it.
    const meta = page.locator('.article-meta').first();
    expect((await meta.boundingBox())!.height).toBeLessThan(48);
  });

  test('the tags choice survives a reload', async ({ page }) => {
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Show tags' }).click();
    await page.reload();
    await page.waitForSelector('.article-row');
    await expect(page.locator('html')).toHaveAttribute('data-tags', 'on');
    await openDrawer(page);
    await expect(page.getByRole('switch', { name: 'Show tags' }))
      .toHaveAttribute('aria-checked', 'true');
  });

  test('a long tag is capped rather than allowed to wrap the line', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The 13ch cap was dropped with the tag row that needed it. The tag is
    // back at phone width, so the cap comes back with it.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [article(1, { topics: ['campeonato-brasileiro-serie-a'] })],
      next_offset: null, diagnosis: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Show tags' }).click();
    await page.locator('.drawer-scrim').click({ position: { x: 340, y: 40 } });

    const tag = (await page.locator('.meta-tag').first().boundingBox())!;
    const viewport = page.viewportSize()!.width;
    expect(tag.width, 'the tag took the whole meta line').toBeLessThan(viewport * 0.4);
    expect((await page.locator('.article-meta').first().boundingBox())!.height)
      .toBeLessThan(48);
  });
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone -g "tags switch shows|tags choice survives|long tag is capped"`
Expected: all three FAIL — `getByRole('switch', { name: 'Show tags' })` resolves to nothing.

- [ ] **Step 3: Create the preference module**

`web/src/tags.ts`:

```ts
/**
 * Whether the reading list shows the topic tag.
 *
 * A fourth display preference beside `theme`, `density` and `photos`, and
 * per-device for the same reason they are.
 *
 * It replaces a breakpoint rather than adding to one. The tag was desktop-only
 * -- `display: none` at base, `inline` only inside the 900px block -- because
 * the meta line is a single line on a phone and the tag is the item that would
 * wrap it. That made it the one thing on the card a reader could not choose,
 * and a switch in the drawer that did nothing on a phone would have been worse
 * than no switch.
 *
 * Defaults to **off**, which is what a phone shows today: the switch then means
 * the same thing on both devices, and a desktop reader turns it on once. The
 * phone's single meta line is protected by the 13ch cap in `App.css`, not by
 * hiding the control.
 *
 * Stored in localStorage beside `theme`, `density`, `photos` and
 * `sidebar-collapsed`: a non-secret display preference, and the sanctioned use
 * of that store.
 */
export type Tags = 'on' | 'off';

const KEY = 'tags';

export function loadTags(): Tags {
  try {
    return localStorage.getItem(KEY) === 'on' ? 'on' : 'off';
  } catch {
    return 'off';
  }
}

export function setTags(value: Tags): void {
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* private mode: the toggle still works, it just forgets */
  }
}

/** Stamped on <html>, so it is one attribute rather than a prop threaded
 *  through every component that renders part of a card. */
export function applyTags(value: Tags): void {
  document.documentElement.dataset.tags = value;
}
```

- [ ] **Step 4: Wire it into the shell**

`web/src/App.tsx` — import beside the other three preferences (after the `photos` import, ~line 18):

```tsx
import { applyTags, loadTags, setTags, type Tags } from './tags';
```

State and effect, directly after the `photos` pair (~line 79):

```tsx
  const [tags, setTagsState] = useState<Tags>(() => loadTags());
  useEffect(() => applyTags(tags), [tags]);
```

Pass it to `Drawer`, beside `photos={photos}` and `setPhotosState={setPhotosState}`:

```tsx
        tags={tags}
        setTagsState={setTagsState}
```

And a palette entry, directly after the `photos` command (~line 283):

```tsx
    { id: 'tags', label: 'Toggle article tags',
      run: () => setTagsState((t) => { const n = t === 'on' ? 'off' : 'on'; setTags(n); return n; }) },
```

- [ ] **Step 5: Add the switch to the drawer**

`web/src/components/Drawer.tsx` — import beside the others:

```tsx
import { setTags, type Tags } from '../tags';
```

Add to `DrawerProps`, beside `photos` and `setPhotosState`:

```tsx
  tags: Tags;
  setTagsState: Dispatch<SetStateAction<Tags>>;
```

Add both names to the destructured parameter list, then render the switch inside `.drawer-settings`, directly after the Compact `Toggle`:

```tsx
            {/* The topic tag was the one thing on the card a reader could not
                choose: desktop-only by breakpoint, because it is the item that
                would wrap the phone's single meta line. This preference
                replaces that breakpoint -- the line is protected by a 13ch cap
                instead -- so the switch means the same thing on both devices.
                `name` diverges from `label` the way Photos and Compact do. */}
            <Toggle
              label="Tags"
              name="Show tags"
              checked={tags === 'on'}
              onChange={(v) => {
                const next = v ? 'on' : 'off';
                setTags(next); setTagsState(next);
              }}
            />
```

- [ ] **Step 6: Make the preference the gate, and cap the tag**

`web/src/App.css` — replace `.meta-tag` and `.meta-dot-tag` (`:1147-1158`) with:

```css
/* A button, so the card's click guard excludes it and it is reachable by Tab --
   but it must read as the plain text the design asks for, not as a chip.
   Hidden unless the drawer's Tags switch is on. That switch replaced a
   `min-width: 900px` gate: the tag was the one item on the card a reader could
   not choose, and a control in the drawer that did nothing at phone width
   would have been worse than none. Its dot goes with it -- a separator left
   behind by a hidden tag is a stray mark. */
.meta-tag {
  display: none;
  flex: none;
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  letter-spacing: inherit;
  color: inherit;
  cursor: pointer;
}
.meta-dot-tag { display: none; }
/* 13ch, back again. The cap went out with the tag row that needed it; the tag
   is rendered at phone width now, where the meta line is a single line and
   this is the item that would wrap it. `inline-block`, not `inline`: an inline
   box has no width to cap and ignores `text-overflow` entirely. */
[data-tags='on'] .meta-tag {
  display: inline-block;
  max-width: 13ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
[data-tags='on'] .meta-dot-tag { display: inline; }
```

Then delete the now-superseded line from the `@media (min-width: 900px)` block (`App.css:1368`):

```
  .meta-tag, .meta-dot-tag { display: inline; }
```

Leave `.meta-tag:hover` in the `@media (hover: hover)` block alone.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd web && npx playwright test mobile.spec.ts --project=phone --project=safari -g "tags switch shows|tags choice survives|long tag is capped"`
Expected: PASS on both projects.

- [ ] **Step 8: Verify the desktop tag still works, behind the switch**

Run: `cd web && npx playwright test --project=desktop`
Expected: PASS. Any desktop test that expects `.meta-tag` to be visible without touching the switch now needs `data-tags='on'` set first — set it through the drawer's switch, not by stamping the attribute, so the test drives the control a reader would.

- [ ] **Step 9: Run the full web suite**

Run: `cd web && npm run typecheck && npm run e2e`
Expected: PASS except the known `visual.spec.ts` drift — the `drawer-*` baselines now hold a fourth switch. Task 8 rebuilds them.

- [ ] **Step 10: Commit**

```bash
git add web/src/tags.ts web/src/App.tsx web/src/components/Drawer.tsx web/src/App.css web/e2e/mobile.spec.ts
git commit -m "feat: a Tags switch in the drawer

A fourth per-device display preference. It replaces the tag's min-width:900px
gate rather than adding to it, so the switch means the same thing on a phone
as on a desktop; the phone's one-line meta is protected by a 13ch cap.
Defaults off, which is what a phone shows today."
```

---

## Task 8: Rebuild the pixel baselines and verify the whole stack

**Model: Sonnet.** Mostly procedural, but it ends in a judgment call — a human has to look at four images before any baseline is written, and the suite is known to be blind to low-contrast movement, so the header change has to be confirmed by measurement rather than by a green run.

**Files:**
- Modify: `web/e2e/visual.spec.ts-snapshots/*.png` (the 8 `list-*` and `drawer-*` baselines; `signin-*` and `single-story-*` should not move)
- Modify: `rss-reader/CLAUDE.md`

**Interfaces:**
- Consumes: Tasks 2–7, all committed.
- Produces: nothing.

- [ ] **Step 1: Confirm which baselines actually moved**

Run: `cd web && npx playwright test visual.spec.ts`
Expected: the eight `list-*` and `drawer-*` snapshots fail — `list-*` for the shorter header and the smaller headline, `drawer-*` for those plus the pill-shaped switches and the new Tags row. `signin-*` and `single-story-*` pass. If a `signin-*` or `single-story-*` snapshot fails, a rule leaked outside the reading list — stop and find it before regenerating anything.

- [ ] **Step 2: Measure what the suite cannot see**

`toHaveScreenshot`'s default threshold is above this palette's hairline contrast, so a moved rule does not register. Confirm the header change by measuring instead:

```bash
cd web && npx playwright test mobile.spec.ts --project=phone \
  -g "stays on screen|on top of a headline|switches are pills|is a headline"
```
Expected: PASS — these four are the measurements that stand in for the pixels.

- [ ] **Step 3: Generate the new images and look at them**

```bash
cd web && npx playwright test visual.spec.ts --update-snapshots
```

Then **open** `e2e/visual.spec.ts-snapshots/list-light-phone-linux.png`, `list-dark-phone-linux.png`, `drawer-light-phone-linux.png` and `drawer-dark-phone-linux.png` and check, by eye:
1. the header is shorter and the hamburger sits inside it, level with the title;
2. the headline is visibly smaller than the old baseline but still outranks the summary;
3. the Photos, Compact and Tags switches are pills, not circles, and the new Tags row sits with the other three;
4. nothing else moved.

Regenerating to make red go away, without looking, is how this suite quietly becomes decoration.

- [ ] **Step 4: Run everything**

```bash
docker compose run --rm web pytest tests/ -q
cd web && npm run typecheck && npm run e2e && npm run build
```

`npm run build` is not redundant with typecheck: neither typecheck nor the dev-server e2e run touches the CSS minifier, and invalid CSS that Vite serves happily has failed `docker compose build` at deploy time before.

- [ ] **Step 5: Verify on the device that reported the defects**

The mocked suite cannot see a real Safari on a real phone, and every defect in this plan was reported from one. Against the deployed stack, on the iPhone 16 Pro, in both Safari and the installed PWA:

1. scroll to the bottom of a long list — the top bar is still there and *Mark all read* works from where you are;
2. no floating bars over the first headline at any scroll position;
3. open the drawer, tap the dimmed area — it closes;
4. Photos and Compact read as pills;
5. drawer → Saved articles: the list matches the count beside it, after a *Mark all read*;
6. drawer → Hidden, then Compact on: no "Hidden: …" line, and long-pressing the score still shows the reason;
7. open any article — the top bar matches the list's header;
8. drawer → Tags on — a topic appears on each card and the meta line stays one line; off again — it goes.

- [ ] **Step 6: Bring `CLAUDE.md` up to date**

Three of its statements are now wrong. Under **Frontend**, amend the `Toolbar.tsx` bullet and the drawer bullet:

- the "One header, not two" bullet gains: *The header is `position: sticky` at z-index 15 and `.drawer-toggle` rides inside it. It was unpinned with the toggle fixed above the drawer — circular, and it cost both Mark-all-read's reachability from the foot of a long list and a clean first headline. The scrim closes the drawer now.*
- a new bullet: *The coarse-pointer tap floor (`min-height: 40px` on every button without `.pill`) is the wrong instrument for a control whose shape carries meaning. `.toggle` opts out and takes a 44px target from `::after`; `.segment` takes a 32px floor. At 40px under `--radius-pill` a 42×26 switch renders as a circle — on touch devices only, which is why it survived so long.*
- the modal bullet gains: *`.modal-nav` uses `.header-action`, the same vocabulary as `.app-header`. `.btn-icon` / `.btn-external` remain for the other screens.*

Also under **Frontend**, two counts are now wrong: *"Three display preferences, all per-device localStorage: `theme`, `density`, `photos`"* becomes **four**, with `tags`; and *"`localStorage` holds four keys"* becomes **five**. Say what `tags` is for: it replaced the topic tag's `min-width: 900px` gate rather than adding to it, so the switch means the same thing on a phone as on a desktop, and the phone's single meta line is held by a 13ch cap instead of by hiding the control. It defaults off.

Under **DB schema**, beside the dismissed-pile paragraph, add: *The Saved list does **not** apply `_visible`, and accepts `hidden` status as well as `summarized`. `dismiss-all` stamps everything the on-screen filter matched, saved articles included, so with the split on, one Mark-all-read emptied Saved while `sidebar_counts` — which never applied the split to `saved` — went on reporting a dozen. A save is a keep, and asking for your keeps is not asking whether you dealt with them.*

- [ ] **Step 7: Commit**

```bash
git add web/e2e/visual.spec.ts-snapshots CLAUDE.md
git commit -m "test: rebuild the phone visual baselines; document the fixes"
```

---

## Task 9: The article list's type is too large and too heavy

**Model: Sonnet.** Small in diff, but it inverts a state the stylesheet already
encodes — dropping the headline to a normal weight makes the *read* rule heavier than
the unread one — and it has to keep a hierarchy that is currently carried by weight.

### Current values (measured on the `phone` project)

```
.article-title    17px / weight 600 / line-height 1.35 / letter-spacing -0.2px
.article-summary  14px / weight 400
desktop override  .article-title { font-size: 20px; line-height: 1.3; letter-spacing: -0.35px }
```

### The trap

`App.css:439` reads:

```css
.article-row.read .article-title { color: var(--color-ink-muted); font-weight: 500; }
```

That 500 exists to *lighten* a read headline against an unread 600. Take the unread
weight to 400 and the rule inverts: read stories become the boldest thing in the list.
The colour shift to `--color-ink-muted` is what should carry read state, and it already
does — so the weight declaration goes rather than being re-tuned.

### The hierarchy question

At 15px/400 against a 14px/400 summary, one pixel and a colour token are all that
separate a headline from its own summary. The summary drops to 13px so the step
survives. The reader asked for "the article fonts" — plural — so this is inside the ask.

The desktop override sets size, line-height and tracking but **not** weight, so the
unbolding reaches desktop whether or not its size changes. Size follows proportionally
(20 → 17) rather than leaving a desktop headline bold-less at its old display size.

**Files:**
- Modify: `web/src/App.css` — `.article-title` (~463), `.article-row.read .article-title`
  (~439), `.article-summary` (~478), the desktop `.article-title` override (~1484)
- Test: `web/e2e/mobile.spec.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks build on. Moves the `list-*` visual baselines (Task 12).

- [ ] **Step 1: Write the failing test**

Add to `web/e2e/mobile.spec.ts`, in the `the top bar and the drawer fit the screen`
describe block:

```ts
  test('the list is set in normal weight, with the summary a step below', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The headline carried weight 600, which on a list of forty stories is a
    // wall of bold. Hierarchy moves onto size and colour: 15px ink over 13px
    // body ink. Both normal weight.
    const title = page.locator('.article-title').first();
    await expect(title).toHaveCSS('font-size', '15px');
    await expect(title).toHaveCSS('font-weight', '400');

    const summary = page.locator('.article-summary').first();
    await expect(summary).toHaveCSS('font-size', '13px');
    // A step, not a tie: the headline must still out-size its own summary.
    const [t, s] = [
      parseFloat(await title.evaluate((el) => getComputedStyle(el).fontSize)),
      parseFloat(await summary.evaluate((el) => getComputedStyle(el).fontSize)),
    ];
    expect(t).toBeGreaterThan(s);
    // ...and they must not be the same colour, or the step is one pixel.
    const [tc, sc] = [
      await title.evaluate((el) => getComputedStyle(el).color),
      await summary.evaluate((el) => getComputedStyle(el).color),
    ];
    expect(tc).not.toBe(sc);
  });

  test('a read story is never bolder than an unread one', async ({ page }) => {
    // `.article-row.read .article-title` set `font-weight: 500` to lighten a
    // read headline against an unread 600. With unread at 400 that rule
    // inverts and read becomes the boldest thing on the screen. Colour is what
    // carries read state.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [
        article(1, { state: { read: true, saved: false, dismissed: false, opinion: null } }),
        article(2, { state: { read: false, saved: false, dismissed: false, opinion: null } }),
      ],
      next_offset: null, diagnosis: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');

    const weight = (sel: string) => page.locator(sel).evaluate(
      (el) => parseInt(getComputedStyle(el).fontWeight, 10));
    const read = await weight('.article-row.read .article-title');
    const unread = await weight('.article-row:not(.read) .article-title');
    expect(read, 'a read headline outweighs an unread one').toBeLessThanOrEqual(unread);
    // And read state is still visible, just not through weight.
    const colours = await Promise.all(['.article-row.read .article-title',
                                       '.article-row:not(.read) .article-title']
      .map((s) => page.locator(s).evaluate((el) => getComputedStyle(el).color)));
    expect(colours[0]).not.toBe(colours[1]);
  });
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && CI=1 npx playwright test mobile.spec.ts --project=phone --workers=2 -g "normal weight|never bolder"`
Expected: the first FAILS on `Expected: "15px" Received: "17px"`. The second **passes today**
(read 500 < unread 600) — it is the regression guard for Step 3, and must still pass after.

- [ ] **Step 3: Set the list in normal weight**

`.article-title` (~463):

```css
.article-title {
  /* 15/400, from 17/600. A reading list is forty headlines in a column, and at
     600 that is a wall of bold with nothing standing out of it because
     everything is. Hierarchy moves onto size and colour instead: 15px
     `--color-ink` over a 13px `--color-ink-body` summary. Tracking goes to 0 --
     negative tracking is a display-size correction and reads as cramped at 15px
     in a normal weight. */
  font-size: 15px;
  line-height: 1.4;
  font-weight: 400;
  letter-spacing: 0;
  color: var(--color-ink);
  text-wrap: pretty;
  cursor: pointer;
}
```

`.article-row.read .article-title` (~439) — drop the weight declaration, keep the colour:

```css
/* Colour only. This used to also set `font-weight: 500`, to lighten a read
   headline against an unread 600; with unread at 400 that inverted and made
   read stories the boldest thing in the list. */
.article-row.read .article-title { color: var(--color-ink-muted); }
```

`.article-summary` (~478) — 14 → 13, so the headline keeps a size step:

```css
.article-summary {
  margin: 0;
  /* 13, from 14. The headline came down to 15; at 14 the two were a pixel
     apart and the card read as one undifferentiated block of text. */
  font-size: 13px;
  line-height: 1.55;
  font-weight: 400;
  color: var(--color-ink-body);
  text-wrap: pretty;
}
```

Desktop override (~1484) — the weight is not restated here, so unbolding reaches desktop
either way; the size follows proportionally rather than leaving a 20px unbold headline:

```css
  /* 17, from 20, tracking down with it. The base rule sets the weight for both
     widths; only size, line-height and tracking are per-width. */
  .article-title { font-size: 17px; line-height: 1.35; letter-spacing: -0.1px; }
```

- [ ] **Step 4: Run both tests**

Run: `cd web && CI=1 npx playwright test mobile.spec.ts --project=phone --project=safari --workers=2 -g "normal weight|never bolder"`
Expected: both PASS on both projects.

- [ ] **Step 5: Re-run the guard tests this could break**

Run: `cd web && CI=1 npx playwright test mobile.spec.ts --project=phone --workers=2 -g "compact mode trades|gets most of the width|is a headline, not a heading|beside the photo"`

`is a headline, not a heading` asserts `font-size: 17px` and `headline > summary + 2`.
Both are now wrong: the size is 15, and 15 − 13 = 2 is not greater than 2. **Update that
test to the new values** — it is the same claim at a new size, so change the numbers and
keep the claim (`toHaveCSS('font-size', '15px')` and `expect(t).toBeGreaterThan(s)`).
Do not delete it and do not weaken it to an inequality that would pass at any size.

If `compact mode trades summaries for stories on screen` fails its
`toBeLessThan(comfortable - 30)`, report it rather than loosening the threshold — a
smaller summary saves fewer pixels when hidden, and that is a real finding about whether
compact still earns its place.

- [ ] **Step 6: Commit**

```bash
git add web/src/App.css web/e2e/mobile.spec.ts
git commit -m "fix: the reading list is set at 15/400, not 17/600

Forty headlines at weight 600 is a wall of bold. Size and colour carry the
hierarchy instead, and the read-state rule loses its font-weight, which
would otherwise have made read stories the boldest thing on the screen."
```

---

## Task 10: The gap between articles is too large

**Model: Haiku.** Two numbers, with the reasoning supplied and the one claim it
invalidates named.

### Current values

`#article-list { gap: 34px }` (~399), and `gap: 40px` inside the
`@media (min-width: 900px)` block (~1468).

`CLAUDE.md` states the rule this changes: *"Whitespace separates the stories — nothing
else does. 34px between cards, 40px on desktop; no dividers, no row background tints."*
The thesis survives — nothing is gaining a divider — but the numbers in that sentence
become wrong and must be updated with the change.

**Files:**
- Modify: `web/src/App.css` (~399 and ~1468), `CLAUDE.md`
- Test: `web/e2e/mobile.spec.ts`

**Interfaces:**
- Consumes: Task 9's smaller type (a tighter gap reads differently against smaller text;
  land Task 9 first).
- Produces: nothing. Moves the `list-*` visual baselines (Task 12).

- [ ] **Step 1: Write the failing test**

```ts
  test('the list is tighter than a screen-and-a-half per story', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // 34px between cards was set when the headline was 19px and bold. Against
    // 15/400 it reads as drift rather than separation. Whitespace is still the
    // only thing dividing the stories -- there are no dividers and no row
    // tints -- there is just less of it.
    await expect(page.locator('#article-list')).toHaveCSS('row-gap', '20px');
    const perScreen = await page.evaluate(() =>
      window.innerHeight /
      (document.querySelector('.article-row') as HTMLElement).getBoundingClientRect().height);
    expect(perScreen, 'fewer than four stories fit a screen').toBeGreaterThan(4);
    // The separation must still be real: no card may touch its neighbour.
    const gaps = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.article-row')];
      return rows.slice(1).map((r, i) =>
        r.getBoundingClientRect().top - rows[i].getBoundingClientRect().bottom);
    });
    expect(Math.min(...gaps)).toBeGreaterThanOrEqual(16);
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && CI=1 npx playwright test mobile.spec.ts --project=phone --workers=2 -g "tighter than a screen"`
Expected: FAIL — `Expected: "20px" Received: "34px"`.

- [ ] **Step 3: Tighten both gaps**

`#article-list` (~399):

```css
#article-list {
  display: flex;
  flex-direction: column;
  /* 20, from 34. That 34 was set against a 19px bold headline; under 15/400 the
     same gap reads as the list drifting apart rather than as separation.
     Whitespace is still the only thing between two stories -- no dividers, no
     row tints -- there is simply less of it needed now. */
  gap: 20px;
  padding: 6px 24px 24px;
  list-style: none;
  margin: 0;
}
```

Desktop (~1468):

```css
  #article-list {
    max-width: 760px;
    /* 24, from 40 -- the same proportion the phone took, against a 760px
       measure that can carry a little more air than a 390px one. */
    gap: 24px;
    padding: 34px 48px 24px;
  }
```

- [ ] **Step 4: Run the test**

Run: `cd web && CI=1 npx playwright test mobile.spec.ts --project=phone --project=safari --workers=2 -g "tighter than a screen"`
Expected: PASS on both.

- [ ] **Step 5: Correct the claim in `CLAUDE.md`**

Find *"Whitespace separates the stories — nothing else does. 34px between cards, 40px on
desktop"* and change the two numbers to **20px** and **24px**. Leave the rest of the
sentence exactly as it is — no dividers, no row background tints and no vote tints all
still hold, and read state is still `opacity: .55` rather than a colour.

- [ ] **Step 6: Commit**

```bash
git add web/src/App.css web/e2e/mobile.spec.ts CLAUDE.md
git commit -m "fix: 20px between stories, 24 on desktop

34 was set against a 19px bold headline. Under 15/400 it read as drift.
Whitespace is still the only separator -- there is just less of it."
```

---

## Task 11: The reader's headline is half the screen

**Model: Sonnet.** One rule, but it is a rule that does not exist yet, and where it is
scoped decides whether it also restyles an unrelated screen.

### Root cause (measured on the `phone` project)

```
.modal-body h1   font-size 32px   font-weight 700   line-height 57.6px
                 a three-line headline is 173px tall
```

There is **no rule for it anywhere**. 32px is the browser default `h1` (`2em` against the
16px root), and 57.6px is `.modal-body`'s `line-height: 1.8` — a body-copy value —
inherited onto a heading. The line-height is doing more damage than the size: 1.8 on a
three-line headline spends 76px on leading alone.

### Scope

`.modal-body h1` is safe. `grep -rn "<h1>" web/src` returns exactly two: `Reader.tsx:64`
and `App.tsx:347`, and the second is inside `.unreachable`, which is not a modal. So the
selector reaches the reader's headline and nothing else. Do **not** restyle bare `h1`.

**Files:**
- Modify: `web/src/App.css` — a new rule beside `.modal-body` (~682)
- Test: `web/e2e/reading.spec.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. Does not move any committed visual baseline — `visual.spec.ts`
  covers the reading list, the drawer, sign-in and single-story, not the reader modal.

- [ ] **Step 1: Write the failing test**

Add to `web/e2e/reading.spec.ts`:

```ts
test('the reader headline is a headline, not a banner', async ({ page }) => {
  // It had no rule at all: 32px was the browser default h1 and the 57.6px
  // line-height was `.modal-body`'s 1.8 -- a body-copy value inherited onto a
  // heading -- so a three-line headline stood 173px tall and the article began
  // below the fold on a phone. The leading was doing more damage than the size.
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
  await page.locator('.article-title').first().click();

  const h1 = page.getByRole('dialog').locator('.modal-body h1');
  await expect(h1).toBeVisible();
  await expect(h1).toHaveCSS('font-size', '16px');
  // The leading is the point: 1.8 on a heading is what made it a banner.
  const lh = await h1.evaluate((el) => parseFloat(getComputedStyle(el).lineHeight));
  expect(lh).toBeLessThanOrEqual(21);
  // At 16px it matches the body copy exactly, so weight is the only thing left
  // saying "heading". It must not be given up too.
  const [hw, pw] = await Promise.all([
    h1.evaluate((el) => parseInt(getComputedStyle(el).fontWeight, 10)),
    page.getByRole('dialog').locator('.modal-body p').first()
      .evaluate((el) => parseInt(getComputedStyle(el).fontWeight, 10)),
  ]);
  expect(hw, 'at body size, weight is all that marks the heading').toBeGreaterThan(pw);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && CI=1 npx playwright test reading.spec.ts --project=phone --workers=2 -g "not a banner"`
Expected: FAIL — `Expected: "16px" Received: "32px"`.

- [ ] **Step 3: Give the reader headline a rule**

Add directly after the `.modal-body` rule (~682):

```css
/* The reader's headline, which until now had no rule at all: 32px was the
   browser's default `h1` and the leading was `.modal-body`'s 1.8 inherited onto
   a heading, so a three-line headline stood 173px tall and pushed the article
   itself below the fold on a phone. Halved, and the leading brought to a
   heading value -- which is where most of the height was.

   At 16px this matches the body copy exactly, so `font-weight` is the only
   thing left marking it as a heading. That is deliberate, and it is why the
   weight is restated here rather than left to the browser.

   Scoped to `.modal-body h1`: the only other `<h1>` in the app is the
   `.unreachable` screen's, which is not inside a modal. */
.modal-body h1 {
  font-size: 16px;
  line-height: 1.25;
  font-weight: 700;
  letter-spacing: -0.2px;
  margin: 0 0 12px;
}
```

- [ ] **Step 4: Run the test**

Run: `cd web && CI=1 npx playwright test reading.spec.ts --project=phone --project=desktop --project=safari --workers=2 -g "not a banner"`
Expected: PASS on all three.

- [ ] **Step 5: Check the reader still reads**

Run: `cd web && CI=1 npx playwright test reading.spec.ts design-system.spec.ts --workers=2`
Expected: PASS. The reader modal's own spec covers the lede, the aside groups and the
original-title line; none of them should move.

- [ ] **Step 6: Commit**

```bash
git add web/src/App.css web/e2e/reading.spec.ts
git commit -m "fix: the reader headline is 16/1.25, not 32/1.8

It had no rule at all -- the browser's default h1 size, with .modal-body's
body-copy leading inherited onto it. A three-line headline was 173px."
```

---

## Task 12: Rebuild the baselines and verify

**Model: Sonnet.** Procedural, ending in a judgement a human has to make.

**Files:**
- Modify: `web/e2e/visual.spec.ts-snapshots/*.png` (the `list-*` set), `CLAUDE.md`

- [ ] **Step 1: Confirm which baselines moved**

Run: `cd web && CI=1 npx playwright test visual.spec.ts --workers=2`
Expected: the four `list-*` snapshots (light/dark × phone/desktop) fail. `drawer-*`,
`signin-*` and `single-story-*` should **pass** — Tasks 9-11 touch the card and the
reader, not the drawer or the auth screens. **If a `drawer-*` or `signin-*` snapshot
fails, stop and report it**: a rule leaked outside the reading list.

- [ ] **Step 2: Generate, then have a human look**

```
cd web && CI=1 npx playwright test visual.spec.ts --workers=2 --update-snapshots
```

Then **stop and hand the images over for inspection before committing them.** Check, by
eye, against the previous baseline: the headlines are smaller and no longer bold; read
stories still recede; the cards are closer together but still read as separate cards
rather than as one column of text; nothing else moved. Regenerating to make red go away,
without looking, is how this suite becomes decoration — and on this branch that rule has
already caught two defects every green test missed.

- [ ] **Step 3: Full verification**

```
cd web && CI=1 npx playwright test --workers=2
cd web && npm run typecheck && npm run build
TEST_DATABASE_URL="postgresql+psycopg://betterread:betterread@localhost:5432/betterread" python3 -m pytest tests/ -q
```
(Backend is unaffected by these three tasks but is the branch's floor; Docker is not
available, so use the local Postgres.)

- [ ] **Step 4: On the device**

The only checks that matter for a change of this kind, on the iPhone 16 Pro, in Safari
and the installed PWA: the feed, Hidden and Saved lists all read comfortably at the new
size; a read story is still visibly read; stories still look like separate stories; and
an article's headline no longer fills the screen before the text begins.

- [ ] **Step 5: Commit**

```bash
git add web/e2e/visual.spec.ts-snapshots CLAUDE.md
git commit -m "test: rebuild the list baselines for the smaller, lighter type"
```

---

## Task 13: Tighten the space between stories again

**Model: Sonnet.** The number is trivial; the judgement is the floor. This is the second
tightening — `d248063` already took the gap 34 → 20 and that is live on news.lan (verified
against the deployed CSS bundle) — so the question is not "is 20 too much" but "where does
a card stop reading as a card".

### What the spacing actually is

The gap is not the whole story. `.article-row` carries its own vertical padding, so the
whitespace a reader sees between two stories is `gap + 2 × row-padding`:

```
phone      20 gap + 8 + 8   = 36px  between cards
desktop    24 gap + 10 + 10 = 44px
compact    20 gap + 6 + 6   = 32px
inside a card:  headline -> summary 8px (`.article-text` gap)
                summary  -> meta   10px (`.article-row` gap)
```

The whole-branch review measured that ratio at **3.6–4.5:1** and called it the thing
keeping cards legible as units. Halve the between-card space and it approaches 2:1, at
which point the space between two stories matches the space inside one and the column
reads as continuous text.

**New values: gap 20 → 14 (phone), 24 → 18 (desktop).** That gives 30px between cards on a
phone against 8px internal — **3.75:1**, still clearly above the point where the ratio
collapses, and a 17% cut in the whitespace a reader scrolls past.

### The existing assertion is measuring the wrong thing

`mobile.spec.ts` asserts `Math.min(...gaps) >= 16`, computed from
`row.getBoundingClientRect().top - previousRow.getBoundingClientRect().bottom`. A bounding
box **includes** the element's own padding, so that expression measures the CSS `gap`
alone and ignores the 8px of padding on each side that a reader actually sees. It
undersells the real separation by 16px, and at `gap: 14` it would fail for a layout that
is in fact well separated.

Fix the measurement rather than lowering the number: assert the **visual** separation —
the gap plus both rows' vertical padding — against a floor that means something.

**Files:**
- Modify: `web/src/App.css` — `#article-list` (~399) and its desktop override (~1501)
- Modify: `web/e2e/mobile.spec.ts` — the gap test
- Modify: `web/e2e/redesign.spec.ts` — the three rhythm assertions pinned to 20/24
- Modify: `CLAUDE.md` — the "20px between cards, 24px on desktop" sentence

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. Moves the `list-*` and `drawer-*` baselines (Task 16).

- [ ] **Step 1: Correct the assertion, then change the value**

Replace the neighbour check in `mobile.spec.ts`'s gap test with one that measures what a
reader sees:

```ts
    // Visual separation, not the CSS gap. A bounding box includes the row's own
    // padding, so `next.top - prev.bottom` is the gap alone and ignores the 8px
    // each row adds on both sides -- it understated the real separation by 16px
    // and would have failed a layout that is in fact well spaced.
    const sep = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.article-row')] as HTMLElement[];
      const pad = (el: HTMLElement) =>
        parseFloat(getComputedStyle(el).paddingTop) + parseFloat(getComputedStyle(el).paddingBottom);
      return rows.slice(1).map((r, i) => {
        const gap = r.getBoundingClientRect().top - rows[i].getBoundingClientRect().bottom;
        return gap + pad(r) / 2 + pad(rows[i]) / 2;
      });
    });
    // 24px is the floor where the space between two stories stops being clearly
    // more than the 8px inside one. At `gap: 14` this measures 30.
    expect(Math.min(...sep), 'two stories are no further apart than one is tall')
      .toBeGreaterThanOrEqual(24);
```

Keep the exact `toHaveCSS('row-gap', ...)` assertion in that test, updated to `'14px'`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && CI=1 npx playwright test mobile.spec.ts --project=phone --workers=2 -g "tighter than a screen"`
Expected: FAIL on `Expected: "14px" Received: "20px"`.

- [ ] **Step 3: Tighten both gaps**

`#article-list` base:

```css
  /* 14, from 20. The gap is not the whole separation -- each row adds 8px of its
     own padding on both sides -- so this is 30px of whitespace between two
     stories, against 8px between a headline and its own summary. Below roughly
     24px those two numbers converge and the column reads as continuous text
     rather than as a list of cards. */
  gap: 14px;
```

Desktop override:

```css
    /* 18, from 24: 38px between cards against a 760px measure. */
    gap: 18px;
```

- [ ] **Step 4: Update every other assertion pinned to the old numbers**

`redesign.spec.ts` pins the rhythm in three places (they were updated from 34/40 to 20/24
one batch ago and will now be stale again). Find them with:

```bash
cd web && grep -n "20px\|24px" e2e/redesign.spec.ts
```

Update the values, keep the claims, and **rename the test whose title names the number**
(it currently says "24px rhythm"). Do not weaken an assertion to make it pass — an earlier
task on this branch's predecessor did exactly that and it took a whole-branch review to
catch.

- [ ] **Step 5: Verify against the FULL suite, not one spec**

Run: `cd web && CI=1 npx playwright test --workers=2`
A scoped run is what let the last rhythm change break three tests unnoticed.

- [ ] **Step 6: Correct `CLAUDE.md`**

The sentence now reading *"Whitespace separates the stories — nothing else does. 20px
between cards, 24px on desktop"* becomes 14px and 18px. Add the fact that makes those
numbers legible: the row's own padding brings the real separation to 30px and 38px, and
the floor is the ratio against the 8px inside a card.

- [ ] **Step 7: Commit**

```bash
git add web/src/App.css web/e2e CLAUDE.md
git commit -m "fix: 14px between stories, 18 on desktop

Second tightening. The gap is not the separation -- each row adds 8px of
padding a side -- so this is 30px between stories against 8px inside one.
The neighbour assertion was measuring the gap alone and understating it."
```

---

## Task 14: Saved and Hidden should read like All feeds

**Model: Haiku.** One shared class and one rule, with the selector trap named.

### What differs now

| Row | Class | Renders as |
|---|---|---|
| All feeds | `.drawer-item.is-all` | 17px / 600 / `--color-ink` (15px at phone width) |
| Saved articles | `.sidebar-feed` | 15px / 400 / `--color-ink-secondary` |
| Hidden | `.sidebar-feed` | 15px / 400 / `--color-ink-secondary` |

`App.css:149` comments the current state as *"All feeds leads its group, and is the only
row that does."* The reader's request is the better reading: **All feeds, Saved and Hidden
are the three top-level lists**, and individual feeds nest *under* All feeds behind the
indent rule. Three peers set alike, with their children a step down, is more truthful than
one lead row and two peers demoted to the size of their own children.

### The trap

`.sidebar-feed` is **shared with every individual feed row** (`.sidebar-feed-nested` in
`Sidebar.tsx`). Restyling `.sidebar-feed` would bump every feed in the list to 17/600 and
erase exactly the distinction this task is trying to make. The lead treatment has to be
opt-in via a class on the three rows that should have it.

`is-all` is the existing hook, and **no spec references it** (`grep -rn "is-all" web/e2e`
returns nothing), so it is free to rename to something that describes the role rather than
one of its three occupants.

**Files:**
- Modify: `web/src/App.css` (~149, ~170, ~1491)
- Modify: `web/src/components/Sidebar.tsx` (the `is-all` row, and `HiddenFeeds`' Hidden button)
- Modify: `web/src/components/Drawer.tsx` (the Saved articles button)
- Test: `web/e2e/design-system.spec.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: the class `is-lead`, used by Task 15's rule grouping. Task 15 must not assume
  `is-all` still exists.

- [ ] **Step 1: Write the failing test**

```ts
test('the three top-level lists are set alike, and their feeds are not', async ({ page }) => {
  // All feeds, Saved and Hidden are peers -- three lists you can be reading.
  // Individual feeds nest under All feeds behind the indent rule, and stay a
  // step down. Saved and Hidden used to render at the size of the feeds they
  // sit above, which read as though they belonged to that level.
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await openDrawer(page);

  const type = (loc: import('@playwright/test').Locator) => loc.evaluate((el) => {
    const c = getComputedStyle(el);
    return `${c.fontSize}/${c.fontWeight}/${c.color}`;
  });

  const all = await type(page.locator('.drawer-item.is-lead'));
  const saved = await type(page.getByRole('button', { name: /Saved articles/ }));
  const hidden = await type(page.getByRole('button', { name: 'Hidden', exact: true }));
  expect(saved, 'Saved does not match All feeds').toBe(all);
  expect(hidden, 'Hidden does not match All feeds').toBe(all);

  // ...and a feed underneath is still visibly subordinate.
  const feed = await type(page.locator('.sidebar-feed-nested').first());
  expect(feed, 'a feed row was promoted to the lead treatment').not.toBe(all);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && CI=1 npx playwright test design-system.spec.ts --project=desktop --workers=2 -g "top-level lists are set alike"`
Expected: FAIL — `.drawer-item.is-lead` matches nothing yet.

- [ ] **Step 3: Rename the hook and widen it to all three**

In `App.css`, replace the three `is-all` occurrences:

```css
/* The three top-level lists -- All feeds, Saved, Hidden -- are peers and are
   set alike. The feeds nest under All feeds behind the indent rule and stay a
   step down; `.sidebar-feed` is shared with those nested rows, so the lead
   treatment is opt-in by class rather than applied to the shared row.
   Was `is-all`, named for one of its three occupants. */
.drawer-item.is-lead,
.sidebar-feed.is-lead { font-size: 17px; font-weight: 600; color: var(--color-ink); }
```

```css
.drawer-item.is-lead .sidebar-feed-count,
.sidebar-feed.is-lead .sidebar-feed-count { color: var(--color-accent); }
```

and in the `max-width: 899px` block, `.drawer-item.is-all { font-size: 15px; }` becomes:

```css
  .drawer-item.is-lead,
  .sidebar-feed.is-lead { font-size: 15px; }
```

In `Sidebar.tsx`, change `drawer-item is-all` to `drawer-item is-lead`, and add `is-lead`
to the Hidden button's class list. In `Drawer.tsx`, add `is-lead` to the Saved articles
button's class list. **Do not** add it to any `.sidebar-feed-nested` row.

- [ ] **Step 4: Run the test and the specs that drive these rows**

```
cd web && CI=1 npx playwright test design-system.spec.ts reading.spec.ts interaction.spec.ts mobile.spec.ts --workers=2
```
Four specs reference `.sidebar-feed`; confirm none of them asserted a size or weight that
this changes, and report anything that did rather than adjusting it silently.

- [ ] **Step 5: Commit**

```bash
git add web/src web/e2e
git commit -m "fix: Saved and Hidden are set like All feeds

They are peers -- three lists you can be reading -- not children of the
feed list they sit above. `is-all` becomes `is-lead`, since it now
describes a role rather than one of its three occupants."
```

---

## Task 15: Rule off the drawer's sections

**Model: Sonnet.** The smallest diff of the three and the one most likely to be judged
wrong, because it partly reverses a documented decision. It needs taste and a reason, not
just a border property.

### What is there now

`.drawer-groups` separates its three groups with `gap: 34px` and nothing else.
`CLAUDE.md` records why: the drawer *"was five all-caps labelled sections (Feeds, Saved,
Settings, You, Admin); the headers are gone, because 34px of space between groups says the
same thing and the labels were the loudest type in the column while saying the least."*
One `.drawer-divider` already exists — 1px of `--color-divider`, inset 28px — but only
above the footer.

**The reader has now used that drawer for a while and says the grouping does not read.**
That is better evidence than the original argument, which was made before anyone lived
with it. But the fix should honour what that decision got right: **the headers are not
coming back.** A rule is not a label; it separates without adding the loudest type in the
column.

### What to build

Extend the existing `.drawer-divider` treatment — same 1px, same `--color-divider`, same
28px inset — to sit **between** the drawer's groups, so the column reads as:

```
  Better News / reader · 139 unread
  ─────────────────────────────────
  All feeds, its feeds, Saved, Hidden, One at a time, Your stats
  ─────────────────────────────────
  Photos · Compact · Tags · Sort · Theme
  ─────────────────────────────────
  Profile · Users · Server settings · Ollama log · Shortcuts · Sign out
```

With rules doing the separating, the 34px gaps can come down — a rule plus 34px of space
is saying the same thing twice. Use the space you reclaim to keep the drawer scrollable in
one screen on a phone.

**Judgement calls that are yours, with the constraints they must respect:**
- The rule goes on the group container, not between individual rows — this separates
  *sections*, not items.
- No rule above the first group or below the last: an edge needs no closing.
- Keep the existing `.drawer-divider` before the footer rather than adding a second
  mechanism next to it; if the new rules make it redundant, remove it and say so.
- Reduce `.drawer-groups`' 34px gap to something that reads with a rule in it, and say in
  the commit what you chose and why.
- `--color-divider` must already exist in all three theme blocks of `index.css` — verify
  rather than assume, and if it only exists in some, that is a finding to report, not to
  paper over with a new token.

**Files:**
- Modify: `web/src/App.css` (`.drawer-groups`, `.drawer-group`, `.drawer-divider`)
- Test: `web/e2e/design-system.spec.ts`

**Interfaces:**
- Consumes: Task 14's `is-lead` — do not reintroduce `is-all`.
- Produces: nothing. Moves the `drawer-*` baselines (Task 16).

- [ ] **Step 1: Verify the token exists in all three theme blocks**

```bash
cd web && grep -n "color-divider" src/index.css
```
Expect three definitions — light `:root`, `[data-theme=dark]`, and the
`prefers-color-scheme` fallback. A token defined in only some blocks flashes the wrong
colour on first paint. **If it is missing from any, report it and stop** rather than
adding a fourth definition.

- [ ] **Step 2: Write the failing test**

```ts
test('the drawer rules off its sections without bringing headers back', async ({ page }) => {
  // The five all-caps section headers were removed on purpose -- they were the
  // loudest type in the column while saying the least -- and 34px of space was
  // meant to say the same thing. After living with it the reader says the
  // grouping does not read. A rule separates without being a label, so the
  // headers stay gone and the sections get an edge.
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await openDrawer(page);

  const ruled = await page.evaluate(() => {
    const groups = [...document.querySelectorAll('.drawer-group')] as HTMLElement[];
    return groups.map((g) => {
      const c = getComputedStyle(g);
      return { top: c.borderTopWidth, colour: c.borderTopColor };
    });
  });
  // Every group but the first is ruled off from the one above it.
  expect(ruled.length).toBeGreaterThan(1);
  expect(ruled.slice(1).every((r) => parseFloat(r.top) >= 1),
    'a group has no rule above it').toBe(true);
  expect(parseFloat(ruled[0].top), 'the first group has a rule above nothing').toBe(0);

  // And no section headers came back with them.
  await expect(page.locator('.drawer-group h2, .drawer-group h3')).toHaveCount(0);
});
```

- [ ] **Step 3: Implement, then run**

```
cd web && CI=1 npx playwright test design-system.spec.ts mobile.spec.ts --workers=2
```
`mobile.spec.ts`'s *"a long feed list does not strand the lower sections"* is the one to
watch: it renders thirty feeds and asserts Sign out and the Ollama log are reachable. If
your spacing changes push them out of reach, that is a real finding.

- [ ] **Step 4: Update `CLAUDE.md`**

Its drawer paragraph still says the groups are separated by space alone. Say what
separates them now, and keep the part that is still true and still load-bearing: the
headers are gone and are not coming back.

- [ ] **Step 5: Commit**

```bash
git add web/src/App.css web/e2e CLAUDE.md
git commit -m "fix: the drawer rules off its sections

Space alone was not reading as grouping. A rule is not a label -- the five
all-caps headers stay gone -- and with an edge doing the separating the
gaps come down."
```

---

## Task 16: Rebuild the baselines and verify

**Model: Sonnet.**

- [ ] **Step 1: Confirm what moved.** `cd web && CI=1 npx playwright test visual.spec.ts --workers=2`
  Expect `list-*` (Task 13) and `drawer-*` (Tasks 13, 14, 15 — the drawer screenshot is
  taken over the reading list, so list changes show behind it) to fail. **`signin-*` and
  `single-story-*` must pass**; either failing means a rule leaked.
- [ ] **Step 2: Generate, then STOP.** `--update-snapshots`, then hand the images over for
  inspection before committing. Two real defects on this branch's predecessors were caught
  at exactly this step and by nothing else.
- [ ] **Step 3: Full verification.**
  ```
  cd web && CI=1 npx playwright test --workers=2
  cd web && npm run typecheck && npm run build
  TEST_DATABASE_URL="postgresql+psycopg://betterread:betterread@localhost:5432/betterread" python3 -m pytest tests/ -q
  ```
- [ ] **Step 4: On the device.** The drawer's three sections read as three; Saved and
  Hidden sit level with All feeds; the stories are tighter without running together.

---

## Task 17: Halve the reading list's rhythm

**Model: Sonnet.** Four coupled values that must move together, and a documented floor
this deliberately goes through.

### The decision, made by the reader

The space between two stories is **30px** on a phone — `gap: 14px` plus `.article-row`'s
8px of padding on each side. They asked for half. Put to them that halving the between-card
space alone would leave 15px between stories against 10px *inside* one (1.5:1, at which the
column reads as continuous text), they chose to **halve the card's own spacing with it**,
keeping the ratio.

```
                        now            after
between cards (phone)   30px           15px    (gap 7 + padding 4 + 4)
between cards (desktop) 38px           19px    (gap 9 + padding 5 + 5)
summary -> meta         10px            5px    (`.article-row` gap)
headline -> summary      8px            4px    (`.article-text` gap)
ratio (phone)           30:10 = 3.0:1  15:5 = 3.0:1
```

**This goes through a floor the previous batch set and documented.** Task 13 concluded
"14px is the floor, not a waypoint — a further tightening has no room", and `CLAUDE.md`
records it. That conclusion held the card's internals fixed; halving them too is the move
that makes another halving possible, and the ratio is preserved rather than spent. Say so
in the comment and in `CLAUDE.md` rather than silently deleting the old claim — the next
person needs to know the floor moved because the whole rhythm scaled, not because someone
overrode it.

**Files:**
- Modify: `web/src/App.css` — `#article-list` (base + the 900px override), `.article-row`
  (base padding + gap, the `max-width: 899px` padding override, the
  `[data-density='compact']` padding), `.article-text`
- Modify: `web/e2e/mobile.spec.ts` (the separation test, both densities),
  `web/e2e/redesign.spec.ts` (three rhythm pins), `CLAUDE.md`

- [ ] **Step 1: Update the tests first, and run them to see them fail.** The separation
  test loops both densities against a floor — that floor is now **15**, and the ratio
  assertion (`sep / inner >= 3`) stays exactly as it is. Do not relax the ratio: it is the
  thing the reader's choice was made to preserve, and it is what tells you the halving is
  proportional rather than just smaller. The three `redesign.spec.ts` pins move 14/18 → 7/9;
  rename the test whose title names the number.

- [ ] **Step 2: Halve all four values.**

```css
#article-list { gap: 7px; }                          /* was 14 */
@media (min-width: 900px) { #article-list { gap: 9px; } }   /* was 18 */
.article-row  { padding: 5px 0; gap: 5px; }          /* was 10px 0, gap 10 */
@media (max-width: 899px) { .article-row { padding: 4px 0; } }   /* was 8 */
[data-density='compact'] .article-row { padding: 4px 0; }        /* was 8 */
.article-text { gap: 4px; }                          /* was 8 */
```

Every one of these carries a comment explaining a number that is about to be wrong. Rewrite
them rather than leaving prose that describes the old rhythm.

- [ ] **Step 3: Verify against the FULL suite.** `CI=1 npx playwright test --workers=2`.
  A scoped run is what let a rhythm change break three tests two batches ago.

- [ ] **Step 4: Correct `CLAUDE.md`.** The whitespace paragraph's numbers, and the
  "14px is the floor" claim — which becomes 7px, with the reason it could move.

---

## Task 18: Halve both feed menus, and give Hidden its missing rule

**Model: Sonnet.** Small, but the obvious one-line fix produces a double rule.

### What is wrong

Both feed menus use **18px** between rows: `.drawer-children` (All feeds' children) and
`.sidebar-group-body` (Hidden's children, and the tag groups). Halve both to **9px**.

The reader also spotted that Hidden's feeds hang off nothing. They are right:

```css
.drawer-children    { border-left: 2px solid var(--color-indent-inactive); padding-left: 16px; }
.sidebar-group-body { padding-left: 21px; }   /* 42px on coarse pointers -- no rule */
```

### The trap

`.sidebar-group-body` is **also** the tag groups (ARGENTINA / TECH / UNTAGGED) that live
*inside* `.drawer-children`, which already draws the rule. Adding `border-left` to
`.sidebar-group-body` puts a second line inside All feeds' children, nested against the
first. Scope it to the Hidden group only.

Prefer giving Hidden's body the **same treatment All feeds' children get**, so there is one
indent rule in the drawer rather than two that must be kept in step — including
`.drawer-children.is-active`'s gold-while-reading behaviour, which Hidden's feeds should
also get when one of them is the list being read. How you reach that (a shared class, a
modifier on the Hidden group) is yours; say in the commit why.

Watch the padding: `.drawer-children` indents 16px, `.sidebar-group-body` 21px (42px
coarse). Hidden's rows must not jump sideways, and its children must stay clear of the
caret's tap target.

- [ ] **Step 1: Write the failing test.** Assert (a) both menus' `row-gap` is 9px, (b)
  Hidden's children sit behind a left border of `--color-indent-inactive` of the same width
  as All feeds' children, and (c) **there is exactly one** such rule between the drawer's
  left edge and a tag-group feed row — the assertion that catches the double-rule trap.
- [ ] **Step 2: Implement, then verify.** Run `design-system.spec.ts`, `mobile.spec.ts` and
  `reading.spec.ts` in full; the thirty-feed reachability test is the one to watch.
- [ ] **Step 3:** Update `CLAUDE.md`'s drawer paragraph if it describes the indent rule as
  belonging only to the feed list.

---

## Task 19: Make the All feeds menu collapsible

**Model: Sonnet.** New state and a new control; the accessibility contract and the
persistence both have to be right.

### What exists to copy

`HiddenFeeds` already does exactly this (`Sidebar.tsx:205-245`): a `useCollapsed()` hook, a
`.sidebar-collapse` caret **after** the row (moved there last batch so the three lead rows
share a left edge — do not undo that), `aria-expanded`, an `aria-label` that names the
action and the target (`Expand Hidden` / `Collapse Hidden`), and `{!shut && <body>}`.

All feeds has no such control: `.drawer-all` holds the lead button and, for an admin, the
manage-feeds pencil. `.drawer-children` always renders.

### Requirements

- The caret goes at the **trailing edge**, after the count, matching Hidden. An admin's row
  also carries the pencil — decide the order, keep both reachable, and keep the three lead
  labels sharing one left edge (there is a test asserting that; it must still pass).
- `aria-expanded` and an `aria-label` naming the action and the target, matching Hidden's
  wording exactly in shape (`Expand All feeds` / `Collapse All feeds`).
- Use the **same `useCollapsed()` hook** with its own key. Do not add a second persistence
  mechanism — check how the hook stores state and whether the key namespace collides.
- Collapsing All feeds hides its children only. It must not change which list is being
  read, must not clear a feed filter, and must leave Saved / Hidden / everything below
  untouched.

- [ ] **Step 1: Write the failing test.** Assert the control exists with the right
  accessible name, that `aria-expanded` tracks state, that clicking hides the feed rows and
  clicking again restores them, that the choice survives a reload, and that collapsing does
  **not** change the current list.
- [ ] **Step 2: Implement, then verify in full.** Include the thirty-feed reachability test
  and the three-lead-rows alignment test explicitly.
- [ ] **Step 3:** `CLAUDE.md` — the drawer paragraph should say both feed menus collapse.

---

## Task 20: Let the text wrap around the photo

**Model: Sonnet.** A layout-model change — flex to float — with three tests measuring the
current arrangement and a clearing problem that is easy to get subtly wrong.

### What the reader sees

The card is a flex row: `.article-text` in one column, `.article-thumb` (76px square) in
another. A flex item cannot flow around its sibling, so when the text runs past 76px the
space beside and below the photo stays empty. The reader calls it "white space under the
image" and wants the headline and summary to wrap around it.

### The markup was already built for this

`ArticleCard.tsx:75-78`:

> *Still a span, not a `<button>`: a button is an atomic inline-level box in every engine,
> so it cannot wrap around a float and gets pushed below one whole.*

and `App.css`, above `.article-title`:

> *A span with role="button", never a `<button>`: a button is an atomic inline-level box in
> every engine, so it can never wrap around anything.*

The headline is a `<span role="button">` **specifically so it can wrap around a float.**
That cost real accessibility work — `role`, `tabIndex` and `onKeyDown` are hand-written to
give back what `<button>` provided. Then `.article-head` was made a flex row, which made
the sacrifice buy nothing. This task collects what was already paid for.

**So: do not convert the headline to a `<button>`, and do not remove the role/tabIndex/
keyboard handler.** They are the reason this is possible.

### The change

`.article-head` becomes a block box; `.article-thumb` floats right (the redesign puts the
photo on the right — keep that side); `.article-text` stops being a flex column and its
`gap` becomes a margin on the headline, since `gap` does not apply outside flex/grid.

### Three things that will bite

1. **Clearing.** `.article-meta` must not wrap around the float — it is a full-width row
   carrying the score, source and the Save/Up/Down actions. It needs to clear, or a short
   card will pull the meta line up beside the photo. Equally the float must not escape the
   card and affect the next one: `.article-head` needs to contain it (`display: flow-root`
   is the modern way; a `::after` clearfix also works). Pick one and say why.
2. **`[data-photos='off']`** hides the thumbnail. With no float, the text must fill the
   width with no leftover margin or reserved space — verify in that mode explicitly.
3. **Compact mode** hides `.article-summary`, so only the headline wraps. A one-line
   headline beside a 76px photo leaves the float taller than its content, and without
   correct clearing the meta line lands beside the photo instead of below it. **Test
   compact explicitly** — it is the case most likely to look wrong.

### The existing tests measure the flex arrangement

Three in `mobile.spec.ts` assert the current layout and must be re-aimed at the goal rather
than deleted:
- *"the headline sits beside the photo, not under it"* — asserts `thumb.width === 76`,
  `title.x < thumb.x`, and the headline starting level with the photo. With a float, the
  headline's box spans the full content width (its line boxes are shortened by the float,
  but the element's box is not), so **`title.x < thumb.x` will no longer mean what it
  meant.** Re-aim it at what a reader can see: the *rendered first line* of the headline
  must not start below the photo's top, and the photo must still be on the right.
- *"the headline gets most of the width"* — `title.width / viewport > 0.4`. Under a float
  the box is wider than the text; decide whether the claim still holds or needs restating
  against the first line's rendered width.
- *"turns the photos off and gives the width back"* (photos toggle) compares headline width
  before and after hiding the photo. Under a float the box width may not change at all
  even though the *text* reflows. Re-aim it at the text, not the box.

**Do not delete any of the three, and do not weaken them into assertions that pass at any
layout.** Each is making a real claim a reader would notice; the measurement has to change,
not the claim.

- [ ] **Step 1: Write the failing test first.** Assert the thing the reader asked for: with
  a headline and summary long enough to run past the photo, a later line of text must begin
  at an x left of the photo *and* extend under it — i.e. the text occupies the full column
  width below the float. Measure with `Range`/`getClientRects()` on the text node rather
  than the element box, since the element box does not tell you where lines actually are.
- [ ] **Step 2: Run it, see it fail** against the flex layout.
- [ ] **Step 3: Implement.** Convert `.article-head` to a block/flow-root, float the thumb
  right with its left and bottom margins, unwind `.article-text`'s flex column into a block
  with a margin between headline and summary, and clear `.article-meta`.
- [ ] **Step 4: Re-aim the three existing tests**, then run the FULL suite.
- [ ] **Step 5: Verify all three display modes** — comfortable, compact, and photos-off —
  and say in the report what the meta line does in each.
- [ ] **Step 6:** Update the comments. `App.css`'s `.article-head` comment describes a flex
  row; `ArticleCard.tsx`'s span comment should now say the float it was waiting for exists.
  `CLAUDE.md` describes the card as "the headline, summary and the thumbnail beside them" —
  make it say the text wraps around the photo.

---

## Task 21: Rebuild the baselines and verify

**Model: Sonnet.**

- [ ] `CI=1 npx playwright test visual.spec.ts --workers=2` — expect `list-*` (Task 17) and
  `drawer-*` plus `single-story-*-desktop` (Tasks 18, 19 — the sidebar is a permanent
  column at that width, so it repaints in every desktop shot). **`signin-*` and
  `single-story-*-phone` must pass**; either failing is a real leak.
- [ ] Regenerate with `--update-snapshots`, then **stop** and hand the images over. I
  inspect before anything is committed — on this plan that rule has caught four defects
  that every green test missed.
- [ ] Full verification: the whole Playwright suite, `npm run typecheck && npm run build`,
  and `TEST_DATABASE_URL=postgresql+psycopg://betterread:betterread@localhost:5432/betterread python3 -m pytest tests/ -q`.
  Docker is not available; do not run the backend concurrently with Playwright.
- [ ] On the device: the list is tighter but the stories still read as separate; both feed
  menus collapse; Hidden's feeds hang off a visible line like All feeds' do.

---

## Task List & Recommended Models

> **Model key** — **Haiku**: the cause is fully diagnosed and the change is a value or a declaration, with no judgment left. **Sonnet**: a contained change that still trades one thing against another, or removes code other callers touch. **Opus**: the fix reverses a decision the codebase argues for in a comment, or changes shared read semantics — the implementer has to re-argue it, not just apply it.

| # | Defect | Root cause | Files | Model |
|---|---|---|---|---|
| **1** | Saved list shows nothing | `dismiss_all` stamps saved rows; `list_for_user`'s dismissed split then hides them, while `sidebar_counts` keeps counting them | `app/repo/articles.py`, `web/src/App.tsx`, `tests/test_api.py` | **Opus** |
| **2** | Top bar scrolls away **+** hamburger over the articles | `.drawer-toggle` is `position: fixed` so it can outrank the drawer, which is why `.app-header` was deliberately unpinned — circular | `web/src/App.css`, `components/Toolbar.tsx`, `e2e/mobile.spec.ts` | **Opus** |
| **3** | Photos / Compact switches are circles | `@media (pointer: coarse) { button:not(.pill) { min-height: 40px } }` floors a 42×26 track under a 999px radius | `web/src/App.css`, `e2e/mobile.spec.ts` | **Sonnet** |
| **4** | Hidden-reason survives compact | compact hides `.article-summary` only; `.hidden-reason` is its own `<p>` | `web/src/App.css`, `e2e/mobile.spec.ts` | **Haiku** |
| **5** | Headline too large in the list | `.article-title` is 19px/-0.35px at phone width | `web/src/App.css`, `e2e/mobile.spec.ts` | **Haiku** |
| **6** | Reader top bar is off-system | `.btn-icon` / `.btn-external` with arrow glyphs, plus a third set of metrics ≤899px, predating `.header-action` | `components/Reader.tsx`, `web/src/App.css`, `e2e/design-system.spec.ts` | **Sonnet** |
| **7** | *(new)* Tags switch in the drawer | The topic tag was gated by `min-width: 900px` and had no control at all; the preference replaces that gate | `web/src/tags.ts`, `App.tsx`, `Drawer.tsx`, `App.css`, `e2e/mobile.spec.ts` | **Sonnet** |
| **8** | — | Baseline rebuild, full verification, device check, docs | `e2e/visual.spec.ts-snapshots`, `CLAUDE.md` | **Sonnet** |
| **9** | *(new)* List type too large and too heavy | `.article-title` at 17/600; the read-state rule's `font-weight: 500` inverts once unread drops to 400 | `web/src/App.css`, `e2e/mobile.spec.ts` | **Sonnet** |
| **10** | *(new)* Gap between articles too large | `#article-list` gap 34px / 40px desktop, set against a 19px bold headline | `web/src/App.css`, `CLAUDE.md`, `e2e/mobile.spec.ts` | **Haiku** |
| **11** | *(new)* Reader headline is half the screen | No rule at all: browser-default 32px `h1` with `.modal-body`'s body-copy `line-height: 1.8` inherited onto it — 173px for three lines | `web/src/App.css`, `e2e/reading.spec.ts` | **Sonnet** |
| **12** | — | Baseline rebuild, verification, device check | `e2e/visual.spec.ts-snapshots`, `CLAUDE.md` | **Sonnet** |
| **13** | *(new)* Space between stories still too large | Second tightening; the neighbour assertion measures the CSS gap alone and ignores the 8px of row padding a side, understating real separation by 16px | `web/src/App.css`, `e2e/mobile.spec.ts`, `e2e/redesign.spec.ts`, `CLAUDE.md` | **Sonnet** |
| **14** | *(new)* Saved/Hidden don't match All feeds | They render 15/400 against All feeds' 17/600, at the size of the feeds they sit above; `.sidebar-feed` is shared with nested feed rows so the lead treatment must be opt-in | `web/src/App.css`, `Sidebar.tsx`, `Drawer.tsx`, `e2e/design-system.spec.ts` | **Haiku** |
| **15** | *(new)* Drawer sections don't read as sections | Separated by 34px of space and nothing else — a decision made before anyone had lived with it | `web/src/App.css`, `e2e/design-system.spec.ts`, `CLAUDE.md` | **Sonnet** |
| **16** | — | Baseline rebuild, verification, device check | `e2e/visual.spec.ts-snapshots` | **Sonnet** |
| **17** | *(new)* Halve the list rhythm | 30px between cards; reader chose to halve the card's internals with it, preserving 3:1 | `web/src/App.css`, `e2e/mobile.spec.ts`, `e2e/redesign.spec.ts`, `CLAUDE.md` | **Sonnet** |
| **18** | *(new)* Halve both feed menus; Hidden's missing indent rule | Both at 18px; `.sidebar-group-body` has no border-left, and it is shared with the tag groups *inside* `.drawer-children`, so the naive fix draws a second nested rule | `web/src/App.css`, `Sidebar.tsx`, `e2e/design-system.spec.ts` | **Sonnet** |
| **19** | *(new)* All feeds menu collapsible | `.drawer-children` always renders; `HiddenFeeds` already has the pattern to copy | `Sidebar.tsx`, `web/src/App.css`, `e2e/design-system.spec.ts` | **Sonnet** |
| **20** | *(new)* White space under the photo | `.article-head` is a flex row, so text cannot flow around the thumbnail — though the headline is a `<span role="button">` built expressly to wrap a float | `web/src/App.css`, `ArticleCard.tsx`, `e2e/mobile.spec.ts`, `CLAUDE.md` | **Sonnet** |
| **21** | — | Baseline rebuild, verification, device check | `e2e/visual.spec.ts-snapshots` | **Sonnet** |

**Order matters.** Task 1 is independent (backend, plus one line of `App.tsx`) and can run alongside Task 2. Tasks 2–7 all edit `App.css` and must run sequentially. Task 8 closes out that first batch.

**Tasks 13–16 are a third batch**, added after Tasks 9–12 shipped as PR #73 and went live
on news.lan (verified against the deployed CSS bundle: it already serves `gap: 20px`, so
Task 13 is a second tightening rather than a stale deploy). Task 14 produces the `is-lead`
class that Task 15 must not assume away; otherwise 13, 14 and 15 are independent. Task 16
is last, for the reason Tasks 8 and 12 were.

**Tasks 9–12 are a second batch**, added after the first shipped as PR #72. Task 10 reads against Task 9's smaller type, so land 9 first; Task 11 is independent of both (it touches the reader modal, not the card) and can go in any order. Task 12 must be last, for the same reason Task 8 was: regenerating baselines before every visual change is in means doing it twice and looking at the wrong images the first time.

---

## Found but deliberately out of scope

Recorded here so the next reader does not have to find them again.

- **`.article-row.hidden` is dead CSS.** `App.css:439-440` styles `.article-row.hidden` (0.65 opacity, a left rule, an italic headline), but `ArticleCard.tsx:52-61` never puts `hidden` in the class list — it carries `s.opinion`, `read`, `saved`, `dismissed` and `focused` only. So hidden articles get none of that treatment; `.hidden-reason` is the only thing marking them. Either the class should be added or the rules dropped. Not touched here because it changes how the Hidden list looks, which nobody asked for.
- **Three more dead `<dialog>` rules.** `App.css:655-668` — the bare `dialog`, `dialog::backdrop` and `dialog[open]` rules. Nothing in `src/` renders a `<dialog>`; `components/Modal.tsx` is a `div[role=dialog]`. Task 6 removes the `dialog#reader-modal` override because it sits inside a block being edited; these three sit in a block that is not, and deleting them belongs in a cleanup pass with the rest.
- **No `viewport-fit=cover`.** `web/index.html` sets `width=device-width, initial-scale=1.0`, so on an iPhone 16 Pro iOS insets the web view itself and `env(safe-area-inset-*)` resolves to 0. Tasks 2 and 6 write `max(14px, env(safe-area-inset-top))`, which is exactly the 14px value today and correct if `viewport-fit=cover` is ever added. Adding it now would mean auditing every horizontal gutter in the app for a landscape inset, which is its own piece of work.

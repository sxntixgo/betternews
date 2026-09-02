# Better News — Whitespace Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the reader's four main surfaces — article list, drawer/sidebar, sign in, and an optional single-story mode — to the "whitespace redesign" canvas: no row tints, no dividers, no score pills, and one combined meta + actions row per story.

**Architecture:** Token-first. `web/src/index.css` is repalletted once (Task 3) and every later task consumes those tokens; `App.css` never gains a hex literal. Components are restyled in place rather than replaced, so routing, data flow and the API contract are untouched. Existing token *names* are remapped to new values rather than deleted, which keeps the seven screens outside this redesign (Settings, Insights, AdminUsers, CallLog, ManageFeeds, Profile, Modal) rendering correctly and keeps `design-system.spec.ts` green.

**Tech Stack:** React 19 + TypeScript + Vite; plain CSS with custom properties; Playwright for tests (`phone`, `desktop`, `safari` projects). No new runtime dependencies — `react` and `react-dom` remain the only two.

**Source design:** Claude Design project `146c5e30-f0b8-4d44-a80b-e6a33dcb46a5`, file `Better News Redesign.dc.html`, handoff `design_handoff_better_news/README.md`. Option ids `1a` `1c` `1d` `2a` `2b` `3a` `3b` `3c` `3d` `4a` `4b` `5a`.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **`App.css` contains no hex literal and no literal `border-radius` except `999px`.** Asserted by `web/e2e/design-system.spec.ts`. A new colour means a new token in `index.css`.
- **Every `var(--token)` used in `App.css` must be defined in `index.css`.** Also asserted; a typo is silent.
- **Never delete an existing token name.** Remap its value. Seven screens outside this redesign consume them.
- **Never link Google Fonts.** `index.css` already records why: "linking Google Fonts is not an option on a LAN-only box that should not phone home, and would hang the page whenever the WAN is down." Source Serif 4 is self-hosted (Task 2).
- **Fidelity is high.** Colours, type sizes, weights, spacing and radii from the handoff are final and matched exactly.
- **Icons are text labels** — "Refresh", "Save", "Up", "Down", "Open". Do not reintroduce the emoji thumbs (`👍` `👎` `★` `☆` `🕐` `↗`) from the current app.
- **Score renders as `Math.round(score * 100)` with no `%` sign**, gold, weight 600.
- **The comment-count slot is `article.duplicate_count`** — decided 2026-09-01; Better News has no comments. Rendered as a bare integer, omitted when `0`.
- **Sign in keeps Username + password.** Decided 2026-09-01. No "Forgot?", no magic link, no email field — `users` has only `username`, `password_hash`, `role`, `must_change_password`.
- **`text-wrap: pretty`** on all headlines and summaries.
- **Focus ring:** 2px gold outline, offset 2px, on all interactive elements.
- **Breakpoint:** desktop collapses to mobile below `900px` — sidebar becomes the overlay drawer, thumbnail returns to 76 × 76, gutters 24px, measure unconstrained.
- **Type scale:** 30 / 27 / 26 / 24 / 20 / 19 / 17 / 15 / 14 / 13 / 12 / 11.5 / 11 px. Weights 400 and 600 only.
- **Spacing:** 4px base. Mobile gutter 24px (28px drawer/sign-in), desktop gutter 48px, sidebar gutter 26px. Story gap 34px mobile / 40px desktop.
- **Radii:** 8px thumbnails, 12px strips, 14px window, 20px story card, 999px pills/toggles. No elevation inside the product.
- **Commit after every task.** Branch: `feat/whitespace-redesign`.

## Execution Rules

- **One subagent at a time.** Never dispatch two concurrently; each task is reviewed before the next is dispatched.
- Each task below names the **model** the subagent runs on.
- A subagent receives only its own task section, plus this header and Global Constraints.

| Task | Title | Model | Status |
|---|---|---|---|
| 1 | Make the web toolchain runnable | haiku | DONE (no code change) |
| 2 | Self-host Source Serif 4 | haiku | DONE |
| 3 | Repalette the design tokens | sonnet | DONE |
| 4 | ArticleCard → one meta + actions row | opus | DONE |
| 5 | List rhythm: no tints, no dividers | sonnet | DONE |
| 6 | Mobile header + "What you missed" strip | sonnet | DONE |
| 7 | Desktop measure, toolbar, responsive collapse | opus | DONE |
| 8 | Drawer → three groups | opus | DONE |
| 9 | Toggles and segmented controls | sonnet | DONE |
| 10 | Sign in restyle | sonnet | DONE |
| 11 | Single-story mode *(optional)* | opus | DONE |
| 12 | Full verification pass | opus | DONE |

## Environment Gate — **RESOLVED 2026-09-01 by Task 1**

Kept for the record. Everything below was true before Task 1 ran and is now fixed; the suite runs in this container.

The dev container **cannot currently run the web tests or the production build**:

- `npx vite build` fails with `MODULE_NOT_FOUND` — `web/node_modules` was installed on macOS, so only `@rolldown/binding-darwin-x64` is present.
- Playwright has no browsers installed (`~/.cache/ms-playwright` is absent).
- `node` is not on `PATH`; a working v22 binary ships with the VS Code server.

Task 1 fixes all three. If it cannot (no network for `npm install`), **the redesign tasks must be executed on the Mac instead** — every task from 4 onward is gated on running Playwright, and a subagent that cannot run its tests cannot follow TDD.

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `web/src/index.css` | Every colour, font, radius. The only file with hex literals. | 2, 3 |
| `web/public/fonts/` | Self-hosted Source Serif 4 woff2 (400, 600). | 2 |
| `web/src/components/ArticleCard.tsx` | One story row: headline, summary, thumb, one meta+actions line. | 4 |
| `web/src/components/Toolbar.tsx` | Mobile header row and desktop toolbar actions. | 6, 7 |
| `web/src/components/Digest.tsx` | The "What you missed" strip. | 6 |
| `web/src/components/Sidebar.tsx` | Feed tree with indent rules. | 8 |
| `web/src/components/Segmented.tsx` | **New.** 2-up and 3-up segmented control. | 9 |
| `web/src/components/Toggle.tsx` | **New.** Track + knob switch. | 9 |
| `web/src/screens/SignIn.tsx` | Sign-in, bottom-weighted on mobile. | 10 |
| `web/src/components/SingleStory.tsx` | **New, optional.** One-story triage mode. | 11 |
| `web/src/App.tsx` | Shell: drawer groups, list container, mode switch. | 6, 7, 8, 11 |
| `web/src/App.css` | All layout and type. No hex, no literal radii. | 3–11 |
| `web/e2e/redesign.spec.ts` | **New.** The redesign's own assertions. | 4–11 |

---

### Task 1: Make the web toolchain runnable — **DONE 2026-09-01**

**Model:** `haiku`

**Outcome:** completed. No repo changes — `package-lock.json` regenerated byte-identical and `dist/` is gitignored, so this task produced no commit. Recorded here so a later reader knows why the environment works.

**What was actually required** (the original steps assumed an `npm` that does not exist on this box — the VS Code server's bundled node ships without it, and there is no npm anywhere on the image):

- [x] **Step 1: Install a real Node toolchain system-wide**

```bash
cd /tmp
VER=$(curl -sS https://nodejs.org/dist/index.json \
  | python3 -c "import json,sys;print([r['version'] for r in json.load(sys.stdin) if r['lts']][0])")
curl -sS -o node.tar.xz "https://nodejs.org/dist/$VER/node-$VER-linux-x64.tar.xz"
tar -xf node.tar.xz && mv "node-$VER-linux-x64" /tmp/node-dist
sudo cp -r /tmp/node-dist/bin/* /usr/local/bin/
sudo cp -r /tmp/node-dist/lib/* /usr/local/lib/
rm -rf /tmp/node-dist /tmp/node.tar.xz
```

Verified: `node --version` → `v24.20.0`, `npm --version` → `11.19.0`, both resolvable from a clean shell with no `PATH` manipulation. Install system-wide rather than into `/tmp` — shell state does not persist between tool calls, so a `/tmp` install forces every later command to re-export `PATH`.

- [x] **Step 2: Reinstall web dependencies for Linux**

```bash
cd web && rm -rf node_modules && npm install
```

Verified: `node_modules/@rolldown/binding-linux-x64-gnu` present. The committed `package-lock.json` did **not** change — do not expect a diff here.

- [x] **Step 3: Verify the build runs**

Run: `cd web && npx vite build`
Expected: `✓ built in …`. Confirmed at 319–455ms.

- [x] **Step 4: Install Playwright browsers and their system libraries**

```bash
cd web
npx playwright install chromium webkit
sudo npx playwright install-deps chromium webkit
```

`install` alone is not enough — it downloads the browsers and then fails host validation on missing `libhyphen.so.0`, `libsecret-1.so.0`, `libatk-1.0.so.0` and others. `install-deps` needs root; passwordless `sudo` is available in this devcontainer.

- [x] **Step 5: Establish the baseline**

Run: `cd web && CI=1 npx playwright test`

**`CI=1` is required.** `playwright.config.ts` sets `channel = process.env.CI ? undefined : 'chrome'`, so without it every Chromium project reaches for an installed Google Chrome that this image does not have. Playwright starts the dev server itself via its `webServer` block, so no app process needs starting by hand.

Baseline recorded 2026-09-01: **430 passed, 34 skipped, 1 flaky.**

⚠️ **Known-marginal test.** `e2e/mobile.spec.ts:178` "compact mode trades summaries for stories on screen" failed on `safari` at 179.3px against a `comfortable - 30` threshold of 149.3px, then passed on retry. It is flaky *before* any redesign work. **Task 5 changes the list gap and Task 9 rebuilds the compact toggle — expect to revisit this assertion there, and do not read its failure as a regression you caused.**

- [x] **Step 6: Commit** — nothing to commit; see Outcome above.

---

### Task 2: Self-host Source Serif 4

**Model:** `haiku`

The handoff says Source Serif 4 "loads from Google Fonts". It must not — see Global Constraints. Two weights are needed: 400 and 600.

**Files:**
- Create: `web/public/fonts/source-serif-4-400.woff2`
- Create: `web/public/fonts/source-serif-4-600.woff2`
- Modify: `web/src/index.css` (add `@font-face` and `--font-serif`)

**Interfaces:**
- Consumes: nothing.
- Produces: CSS token `--font-serif`, usable as `font-family: var(--font-serif)`. Tasks 8, 10 and 11 use it for the wordmark and long-form headlines.

- [ ] **Step 1: Fetch the two weights**

```bash
cd /workspaces/repositories/rss-reader/web/public && mkdir -p fonts && cd fonts
curl -sSL -o source-serif-4-400.woff2 \
  "https://cdn.jsdelivr.net/fontsource/fonts/source-serif-4@latest/latin-400-normal.woff2"
curl -sSL -o source-serif-4-600.woff2 \
  "https://cdn.jsdelivr.net/fontsource/fonts/source-serif-4@latest/latin-600-normal.woff2"
ls -la
```

Expected: two files, each roughly 20–40 KB. If the download fails (no WAN), stop and report — do **not** fall back to a Google Fonts `<link>`.

- [ ] **Step 2: Declare the faces in `index.css`**

Add at the very top of `web/src/index.css`, above the existing comment block:

```css
/* Self-hosted, never linked. A LAN-only box should not phone home, and a
   Google Fonts <link> hangs first paint whenever the WAN is down -- which on
   this stack is a normal condition, not an outage. `swap` so the fallback
   renders immediately and the serif swaps in when it lands. */
@font-face {
  font-family: 'Source Serif 4';
  src: url('/fonts/source-serif-4-400.woff2') format('woff2');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: 'Source Serif 4';
  src: url('/fonts/source-serif-4-600.woff2') format('woff2');
  font-weight: 600;
  font-style: normal;
  font-display: swap;
}
```

- [ ] **Step 3: Add the token**

In the `:root` block of `index.css` that defines `--font-ui`, add below it:

```css
  /* Wordmark and long-form headlines only. Body and UI stay sans. */
  --font-serif: 'Source Serif 4', Georgia, 'Times New Roman', serif;
```

- [ ] **Step 4: Verify the font is served**

Run: `node ./node_modules/.bin/vite build && ls dist/fonts/`
Expected: both woff2 files present in `dist/fonts/`.

- [ ] **Step 5: Commit**

```bash
git add web/public/fonts web/src/index.css
git commit -m "feat: self-host Source Serif 4 rather than linking Google Fonts"
```

---

### Task 3: Repalette the design tokens

**Model:** `sonnet`

The single riskiest task: it changes every colour in the app at once. Existing token names keep working with new values; new names are added for what the redesign introduces.

**Files:**
- Modify: `web/src/index.css`

**Interfaces:**
- Consumes: `--font-serif` from Task 2.
- Produces: the token vocabulary every later task uses. Exact names below — later tasks reference these spellings and nothing else.

- [ ] **Step 1: Replace the light `:root` palette**

In `web/src/index.css`, replace the body of the first `:root { ... }` block (the light palette, from `--color-bg` through `--overlay-bg`) with:

```css
  /* ---------- Light palette (redesign) ---------- */
  --color-bg: #faf9f7;
  --color-surface: #f4f2ec;
  --color-surface-2: #f4f2ec;
  --color-surface-accent: #f3efe4;
  --color-surface-story: #faf8f3;
  --color-shell-story: #16160f;
  --color-segment-selected: #ffffff;

  --color-ink: #16160f;
  --color-ink-secondary: #4c4740;
  --color-ink-body: #7d776d;
  --color-ink-muted: #8f897f;
  --color-ink-meta: #a8a29a;
  --color-ink-faint: #b3ada3;
  --color-ink-disabled: #cfc9bf;

  --color-hairline: #e8e3d9;
  --color-hairline-strong: #ddd7cb;
  --color-field-underline: #ddd7cb;
  --color-divider: #eee9e0;
  --color-indent-active: #ede6d6;
  --color-indent-inactive: #f2eee6;
  --color-track: #eae6dc;
  --color-track-2: #f0ede6;
  --color-toggle-off: #e6e1d6;

  --color-accent: #8a6d2f;
  --color-on-accent: #fdfbf5;
  --color-gold-strong: #4a3a12;
  --color-gold-soft: #8a7c58;
  --color-gold-pill-surface: #f0e7d2;
  --color-gold-pill-ink: #7d6224;

  --color-saved: #8a6d2f;
  --color-focus: #8a6d2f;

  --color-danger: #8a3a2a;
  --color-danger-surface: #f7ecea;
  --color-success: #2d7a3a;
  --color-success-surface: #e8f3ea;
  --color-warning: #7d4e00;
  --color-warning-surface: #f3efe4;

  /* Kept as names so unredesigned screens still resolve, but neutralised:
     the redesign removes vote tints from rows entirely. */
  --color-like-surface: transparent;
  --color-dislike-surface: transparent;

  --color-offline-surface: #7d4e00;
  --color-offline-ink: #fdfbf5;

  --color-placeholder-label: #a8a094;
  --placeholder-stripes: repeating-linear-gradient(135deg, #eae5db 0 6px, #f4f0e8 6px 12px);

  --overlay-bg: rgba(22, 22, 15, 0.38);

  color-scheme: light;
```

- [ ] **Step 2: Replace the dark palette**

Replace the body of `[data-theme='dark'] { ... }` with:

```css
  --color-bg: #141310;
  --color-surface: #1b1a15;
  --color-surface-2: #1b1a15;
  --color-surface-accent: #211f19;
  --color-surface-story: #1b1a15;
  --color-shell-story: #0f0e0b;
  --color-segment-selected: #332f26;

  --color-ink: #f4f1e9;
  --color-ink-secondary: #cec8ba;
  --color-ink-body: #918a7d;
  --color-ink-muted: #7c766a;
  --color-ink-meta: #7c766a;
  --color-ink-faint: #6d6659;
  --color-ink-disabled: #5d574c;

  --color-hairline: #26241d;
  --color-hairline-strong: #2e2b23;
  --color-field-underline: #2e2b23;
  --color-divider: #26241d;
  --color-indent-active: #4a4128;
  --color-indent-inactive: #2b2922;
  --color-track: #211f19;
  --color-track-2: #211f19;
  --color-toggle-off: #2e2b23;

  --color-accent: #c8a34e;
  --color-on-accent: #1a1509;
  --color-gold-strong: #e8dcbd;
  --color-gold-soft: #928968;
  --color-gold-pill-surface: #3a3323;
  --color-gold-pill-ink: #e8dcbd;

  --color-saved: #c8a34e;
  --color-focus: #c8a34e;

  --color-danger: #d9604a;
  --color-danger-surface: #2a1410;
  --color-success: #52c46a;
  --color-success-surface: #16281a;
  --color-warning: #d4a055;
  --color-warning-surface: #211f19;

  --color-like-surface: transparent;
  --color-dislike-surface: transparent;

  --color-offline-surface: #5a4310;
  --color-offline-ink: #f4f1e9;

  --color-placeholder-label: #6d6659;
  --placeholder-stripes: repeating-linear-gradient(135deg, #26241d 0 6px, #2e2b23 6px 12px);

  --overlay-bg: rgba(0, 0, 0, 0.6);

  color-scheme: dark;
```

- [ ] **Step 3: Mirror dark into the pre-hydration fallback**

The `@media (prefers-color-scheme: dark) { :root:not([data-theme]) { ... } }` block must list the **same declarations as Step 2, verbatim**. Copy them in. This block covers first paint before `theme.ts` stamps `data-theme`; a mismatch flashes the light palette.

- [ ] **Step 4: Update the UI font stack and radii**

In the `:root` block holding `--font-ui`, replace that declaration and add the new radii:

```css
  --font-ui: 'Helvetica Neue', Helvetica, -apple-system, BlinkMacSystemFont,
    'Segoe UI', Roboto, Arial, sans-serif;
```

and below `--radius-lg`:

```css
  /* Redesign radii. `sm`/`md`/`lg` stay for the screens outside this work. */
  --radius-thumb: 8px;
  --radius-strip: 12px;
  --radius-window: 14px;
  --radius-story: 20px;
```

- [ ] **Step 5: Verify the token discipline still holds**

Run: `node ./node_modules/.bin/playwright test design-system.spec.ts --project=desktop`
Expected: PASS — in particular "every token App.css uses is actually defined". If it fails, a token name was deleted rather than remapped; restore the name.

- [ ] **Step 6: Commit**

```bash
git add web/src/index.css
git commit -m "feat: repalette tokens to the whitespace redesign"
```

---

### Task 4: ArticleCard → one meta + actions row

**Model:** `opus`

The core of the redesign. Four rows (score/reading-time/Open, star/thumbs, source/age/kind/topics, dup-note) collapse into one line: score · source · age · duplicates on the left, Save / Up / Down on the right.

**Files:**
- Modify: `web/src/components/ArticleCard.tsx` (full rewrite of the returned JSX)
- Modify: `web/src/App.css` (`.article-row` and children)
- Create: `web/e2e/redesign.spec.ts`

**Interfaces:**
- Consumes: tokens `--color-ink`, `--color-ink-body`, `--color-ink-meta`, `--color-ink-faint`, `--color-accent`, `--color-saved`, `--radius-thumb`, `--placeholder-stripes` from Task 3.
- Produces: DOM contract relied on by Tasks 5, 7 and 12 —
  - root `article.article-row#card-<id>`
  - `.article-head` (text column + thumb), `.article-title`, `.article-summary`
  - `.article-thumb` (`<img>`), 76 × 76 mobile
  - `.article-meta` — **exactly one per card**
  - `.meta-score`, `.meta-source`, `.meta-age`, `.meta-dupes`
  - `.article-actions` containing three `<button>`s labelled `Save`/`Saved`, `Up`, `Down`
  - Props unchanged: `{ article, onOpen, onVote, onSave, onTopic?, feedName?, focused? }`. `onTopic` becomes unused on mobile but stays in the signature — Task 7 uses it for the desktop tag.

- [ ] **Step 1: Write the failing test**

Create `web/e2e/redesign.spec.ts`:

```ts
import { expect, test } from '@playwright/test';
import { article, mockApi, signedIn } from './fixtures';

test.describe('story row', () => {
  test('is one meta+actions line, not four rows', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const row = page.locator('#card-1');
    await expect(row.locator('.article-meta')).toHaveCount(1);
    // The pill, the topic chips and the Open link were the other three rows.
    await expect(row.locator('.score-badge')).toHaveCount(0);
    await expect(row.locator('.topic-chips')).toHaveCount(0);
  });

  test('shows the score as a bare number in gold, no percent sign', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    // fixtures' article() scores 0.8.
    await expect(page.locator('#card-1 .meta-score')).toHaveText('80');
  });

  test('actions are text labels, never emoji', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const actions = page.locator('#card-1 .article-actions');
    await expect(actions.getByRole('button', { name: 'Save' })).toBeVisible();
    await expect(actions.getByRole('button', { name: 'Up' })).toBeVisible();
    await expect(actions.getByRole('button', { name: 'Down' })).toBeVisible();
    await expect(actions).not.toContainText(/[👍👎★☆]/);
  });

  test('saving switches the label to its active form', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.locator('#card-1 .article-actions').getByRole('button', { name: 'Save' }).click();
    await expect(
      page.locator('#card-1 .article-actions').getByRole('button', { name: 'Saved' }),
    ).toBeVisible();
  });

  test('duplicate count fills the slot the mock labelled comments', async ({ page }) => {
    await signedIn(page);
    await mockApi(page, [article(1, { duplicate_count: 3 })]);
    await page.goto('/');
    await expect(page.locator('#card-1 .meta-dupes')).toHaveText('3');
  });
});
```

**Note:** `mockApi` currently takes only `page`. If it does not accept a second argument for the article list, extend it in `web/e2e/fixtures.ts` to `mockApi(page: Page, articles: Article[] = [article(1), article(2), article(3)])` and use that array for the `/articles` route, preserving current behaviour when the argument is omitted.

- [ ] **Step 2: Run the test to verify it fails**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone`
Expected: FAIL — `.article-meta` resolves 0 elements, `.score-badge` resolves 1.

- [ ] **Step 3: Rewrite the component's JSX**

Replace everything from `return (` to the closing `);` in `web/src/components/ArticleCard.tsx` with:

```tsx
  const score = article.score === null ? null : Math.round(article.score * 100);

  return (
    <article className={classes} id={`card-${article.id}`} onClick={openFromBody}>
      {/* Two rows now, not four. The story, then one line carrying everything
          a reader reads *and* everything they press. The four-row card put the
          score, the buttons, the source and the tags on separate lines, which
          is most of the vertical space this redesign reclaims. */}
      <div className="article-head">
        <div className="article-text">
          {/* Still a span, not a <button>: a button is an atomic inline-level
              box in every engine, so it cannot wrap around a float and gets
              pushed below one whole. role/tabIndex/onKeyDown give back exactly
              what <button> provided. */}
          <span
            className="article-title"
            role="button"
            tabIndex={0}
            onClick={() => onOpen(article)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onOpen(article);
              }
            }}
          >
            {article.title}
          </span>
          {article.summary && <p className="article-summary">{article.summary}</p>}
          {article.hidden && article.score_reason && (
            <p className="hidden-reason">Hidden: {article.score_reason}</p>
          )}
        </div>
        {article.thumbnail_url && (
          <img className="article-thumb" src={article.thumbnail_url} alt="" loading="lazy" />
        )}
      </div>

      <div className="article-meta">
        <div className="meta-facts">
          {score !== null && (
            <span className="meta-score" title={article.score_reason ?? ''}>
              {score}
            </span>
          )}
          {feedName && <span className="meta-source">{feedName}</span>}
          {relativeTime(article.published_at) && (
            <>
              <span className="meta-dot">·</span>
              <span className="meta-age">{relativeTime(article.published_at)}</span>
            </>
          )}
          {article.duplicate_count > 0 && (
            <>
              <span className="meta-dot">·</span>
              {/* The mock's "comment count" slot. Better News has no comments;
                  this is how many other feeds carried the same story. */}
              <span className="meta-dupes" title="Other feeds carrying this story">
                {article.duplicate_count}
              </span>
            </>
          )}
        </div>

        <div className="article-actions">
          <button
            className="action"
            aria-pressed={s.saved}
            onClick={() => onSave(article)}
          >
            {s.saved ? 'Saved' : 'Save'}
          </button>
          <button
            className="action"
            aria-pressed={s.opinion === 'liked'}
            disabled={s.opinion === 'liked'}
            onClick={() => onVote(article, 1)}
          >
            Up
          </button>
          <button
            className="action"
            aria-pressed={s.opinion === 'disliked'}
            disabled={s.opinion === 'disliked'}
            onClick={() => onVote(article, -1)}
          >
            Down
          </button>
        </div>
      </div>
    </article>
  );
```

Delete the now-unused `original-title` and `dup-note` paragraphs. Keep the `openFromBody` guard and the `classes` computation exactly as they are.

- [ ] **Step 4: Add the styles**

In `web/src/App.css`, replace the existing `.article-row` rule and its children with:

```css
.article-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
}
.article-head { display: flex; gap: 16px; align-items: flex-start; }
.article-text { flex: 1; display: flex; flex-direction: column; gap: 8px; min-width: 0; }

.article-title {
  font-size: 19px;
  line-height: 1.32;
  font-weight: 600;
  letter-spacing: -0.35px;
  color: var(--color-ink);
  text-wrap: pretty;
  cursor: pointer;
}
.article-summary {
  margin: 0;
  font-size: 14px;
  line-height: 1.55;
  font-weight: 400;
  color: var(--color-ink-body);
  text-wrap: pretty;
}
.article-thumb {
  width: 76px;
  height: 76px;
  flex: none;
  border-radius: var(--radius-thumb);
  object-fit: cover;
  background: var(--placeholder-stripes);
}

.article-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 11px;
  line-height: 1;
  font-weight: 400;
  letter-spacing: 0.04em;
  color: var(--color-ink-meta);
}
.meta-facts { display: flex; align-items: center; gap: 8px; min-width: 0; }
.meta-score { color: var(--color-accent); font-weight: 600; }

.article-actions { display: flex; gap: 18px; flex: none; }
.article-actions .action {
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  font-size: 12px;
  color: var(--color-ink-faint);
  cursor: pointer;
}
.article-actions .action[aria-pressed='true'] { color: var(--color-accent); }
.article-actions .action:disabled { cursor: default; }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone`
Expected: 5 passed.

- [ ] **Step 6: Run the whole suite for regressions**

Run: `node ./node_modules/.bin/playwright test`
Expected: all pass. `reading.spec.ts` and `mobile.spec.ts` assert against the old card; **update those assertions to the new class names rather than reverting the component.** Report every spec changed.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/ArticleCard.tsx web/src/App.css web/e2e
git commit -m "feat: collapse the story card to one meta and actions row"
```

---

### Task 5: List rhythm — no tints, no dividers

**Model:** `sonnet`

**Files:**
- Modify: `web/src/App.css`
- Modify: `web/e2e/redesign.spec.ts`

**Interfaces:**
- Consumes: `.article-row` and `.article-meta` from Task 4.
- Produces: `.article-list` with `gap: 34px` and no separators; `.article-row.read` at `opacity: .55`.

- [ ] **Step 1: Write the failing test**

Append to `web/e2e/redesign.spec.ts`:

```ts
test.describe('list rhythm', () => {
  test('stories are separated by space, not rules or tints', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const row = page.locator('#card-1');
    const styles = await row.evaluate((el) => {
      const cs = getComputedStyle(el);
      return {
        bg: cs.backgroundColor,
        borderBottom: cs.borderBottomWidth,
        gap: getComputedStyle(el.parentElement as HTMLElement).rowGap,
      };
    });
    expect(styles.bg).toBe('rgba(0, 0, 0, 0)');
    expect(styles.borderBottom).toBe('0px');
    expect(styles.gap).toBe('34px');
  });

  test('a read story is dimmed rather than tinted', async ({ page }) => {
    await signedIn(page);
    await mockApi(page, [article(1, { state: { read: true, saved: false, dismissed: false, opinion: null } })]);
    await page.goto('/');
    const row = page.locator('#card-1');
    await expect(row).toHaveClass(/read/);
    expect(await row.evaluate((el) => getComputedStyle(el).opacity)).toBe('0.55');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "list rhythm"`
Expected: FAIL — gap is not `34px`, and `.article-row.liked` still paints a surface.

- [ ] **Step 3: Implement**

In `web/src/App.css`:

```css
.article-list {
  display: flex;
  flex-direction: column;
  gap: 34px;
  padding: 6px 24px 0;
  list-style: none;
  margin: 0;
}
/* Read is expressed by weight, not by a background. */
.article-row.read { opacity: 0.55; }
```

Then **delete** every rule that paints a row background or draws a separator between rows: the `.article-row.liked`, `.article-row.disliked`, `.article-row.saved` surface fills, `.article-row + .article-row` borders, and the `.article-row.swipe-like-active` / `.swipe-dismiss-active` tints. Swipe feedback becomes transform-only — if a rule sets both `transform` and `background`, keep the transform and drop the background.

- [ ] **Step 4: Run to verify passing**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "list rhythm"`
Expected: 2 passed.

- [ ] **Step 5: Full suite**

Run: `node ./node_modules/.bin/playwright test`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/App.css web/e2e/redesign.spec.ts
git commit -m "feat: separate stories with whitespace instead of tints and rules"
```

---

### Task 6: Mobile header and the "What you missed" strip

**Model:** `sonnet`

**Files:**
- Modify: `web/src/components/Toolbar.tsx`
- Modify: `web/src/components/Digest.tsx`
- Modify: `web/src/App.css`
- Modify: `web/e2e/redesign.spec.ts`

**Interfaces:**
- Consumes: tokens `--color-surface-accent`, `--color-gold-strong`, `--color-gold-soft`, `--color-accent`, `--color-on-accent`, `--radius-strip`, `--radius-pill`.
- Produces: `.app-header` (padding `52px 24px 16px`, column, gap 18px); `.header-title` cluster with `.hamburger`, `All feeds`, `.unread-count`; `.header-actions` with `Refresh`, `Mark all read`, `Search`; `.missed-strip` with `.missed-title`, `.missed-sub`, and a `Read` button.

Copy pattern for the strip subtitle: `"<N> stories since <weekday> · <N> min summary"`.

- [ ] **Step 1: Write the failing test**

Append to `web/e2e/redesign.spec.ts`:

```ts
test.describe('mobile header', () => {
  test('carries the three text actions with Search at full strength', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const actions = page.locator('.header-actions');
    await expect(actions.getByText('Refresh')).toBeVisible();
    await expect(actions.getByText('Mark all read')).toBeVisible();
    await expect(actions.getByText('Search')).toBeVisible();
  });

  test('the missed strip is the first list item and is not sticky', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const strip = page.locator('.missed-strip');
    await expect(strip).toBeVisible();
    expect(await strip.evaluate((el) => getComputedStyle(el).position)).toBe('static');
    await expect(strip.getByRole('button', { name: 'Read' })).toBeVisible();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "mobile header"`
Expected: FAIL — `.header-actions` and `.missed-strip` do not exist.

- [ ] **Step 3: Implement the header**

In `web/src/components/Toolbar.tsx`, render on mobile:

```tsx
<header className="app-header">
  <div className="header-row">
    <div className="header-title">
      <button className="hamburger" aria-label="Open menu" onClick={onOpenDrawer}>
        <span /><span />
      </button>
      <span className="header-name">{title}</span>
      <span className="unread-count">{unread}</span>
    </div>
    <div className="header-actions">
      <button className="header-action" onClick={onRefresh}>
        {polling ? 'Refreshing…' : 'Refresh'}
      </button>
      <button className="header-action" onClick={onDismissAll}>Mark all read</button>
      <button className="header-action is-ink" onClick={onSearch}>Search</button>
    </div>
  </div>
</header>
```

Wire `onOpenDrawer`, `onRefresh`, `onDismissAll`, `onSearch`, `title`, `unread` and `polling` from the props `Toolbar` already receives in `App.tsx`; add any that are missing to its props type and pass them from `App.tsx`. "Mark all read" calls the same handler the current "Dismiss all" control calls (`POST /articles/dismiss-all`) — the label changes, the endpoint does not.

- [ ] **Step 4: Implement the strip**

In `web/src/components/Digest.tsx`, replace the outer markup with:

```tsx
<div className="missed-strip">
  <div className="missed-text">
    <div className="missed-title">What you missed</div>
    <div className="missed-sub">{storyCount} stories since {sinceLabel} · {readMinutes} min summary</div>
  </div>
  <button className="missed-cta" onClick={onOpen}>Read</button>
</div>
```

Derive `storyCount`, `sinceLabel` and `readMinutes` from the digest payload the component already receives. Render nothing when there is no digest.

- [ ] **Step 5: Add the styles**

```css
.app-header { display: flex; flex-direction: column; gap: 18px; padding: 52px 24px 16px; }
.header-row { display: flex; align-items: center; justify-content: space-between; }
.header-title { display: flex; align-items: center; gap: 14px; }
.header-name { font-size: 17px; font-weight: 600; letter-spacing: -0.2px; color: var(--color-ink); }
.unread-count { font-size: 12px; font-weight: 400; color: var(--color-ink-meta); }

.hamburger {
  width: 18px; display: flex; flex-direction: column; gap: 4px;
  background: none; border: 0; padding: 0; cursor: pointer;
}
.hamburger span { height: 1.5px; background: var(--color-ink); }

.header-actions { display: flex; align-items: center; gap: 20px; }
.header-action {
  background: none; border: 0; padding: 0; font: inherit;
  font-size: 13px; font-weight: 400; color: var(--color-ink-muted); cursor: pointer;
}
.header-action.is-ink { color: var(--color-ink); }

.missed-strip {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 16px;
  border-radius: var(--radius-strip);
  background: var(--color-surface-accent);
  position: static;
}
.missed-text { flex: 1; min-width: 0; }
.missed-title { font-size: 13px; font-weight: 600; line-height: 1.2; color: var(--color-gold-strong); }
.missed-sub { margin-top: 4px; font-size: 11.5px; font-weight: 400; line-height: 1.3; color: var(--color-gold-soft); }
.missed-cta {
  flex: none; padding: 8px 14px; border: 0;
  border-radius: var(--radius-pill);
  background: var(--color-accent);
  color: var(--color-on-accent);
  font-size: 12px; font-weight: 600; cursor: pointer;
}
```

- [ ] **Step 6: Run to verify passing**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "mobile header"`
Expected: 2 passed.

- [ ] **Step 7: Full suite, then commit**

Run: `node ./node_modules/.bin/playwright test`

```bash
git add web/src/components/Toolbar.tsx web/src/components/Digest.tsx web/src/App.css web/e2e/redesign.spec.ts
git commit -m "feat: mobile header and what-you-missed strip"
```

---

### Task 7: Desktop measure, toolbar, responsive collapse

**Model:** `opus`

**Files:**
- Modify: `web/src/App.css`
- Modify: `web/src/components/ArticleCard.tsx` (desktop tag)
- Modify: `web/e2e/redesign.spec.ts`

**Interfaces:**
- Consumes: `.article-list`, `.article-row`, `.article-thumb`, `.article-meta` from Tasks 4–5; `.missed-strip` from Task 6.
- Produces: `.site-content` toolbar at `padding: 26px 48px 0`; `.filter-field` underline input; `.article-list` at `max-width: 760px` with `gap: 40px` above 900px; `.meta-tag` (one plain-text topic, desktop only).

- [ ] **Step 1: Write the failing test**

```ts
test.describe('desktop layout', () => {
  test.use({ viewport: { width: 1280, height: 860 } });

  test('the list is held to a 760px measure with a 40px rhythm', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const list = page.locator('.article-list');
    const box = await list.boundingBox();
    expect(box!.width).toBeLessThanOrEqual(760);
    expect(await list.evaluate((el) => getComputedStyle(el).rowGap)).toBe('40px');
  });

  test('the thumbnail is 104 x 78 on desktop', async ({ page }) => {
    await signedIn(page);
    await mockApi(page, [article(1, { thumbnail_url: 'https://example.com/p.jpg' })]);
    await page.goto('/');
    const box = await page.locator('#card-1 .article-thumb').boundingBox();
    expect(Math.round(box!.width)).toBe(104);
    expect(Math.round(box!.height)).toBe(78);
  });

  test('the filter field is an underline, not a bordered box', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const cs = await page.locator('.filter-field').evaluate((el) => {
      const s = getComputedStyle(el);
      return { top: s.borderTopWidth, bottom: s.borderBottomWidth };
    });
    expect(cs.top).toBe('0px');
    expect(cs.bottom).toBe('1px');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=desktop -g "desktop layout"`
Expected: FAIL on all three.

- [ ] **Step 3: Implement**

Mobile-first: the rules from Tasks 4–6 are the base; desktop is one media query.

```css
@media (min-width: 900px) {
  .article-list { max-width: 760px; gap: 40px; padding: 34px 48px 0; }
  .article-head { gap: 22px; }
  .article-title { font-size: 20px; line-height: 1.3; }
  .article-thumb { width: 104px; height: 78px; }
  .article-meta { font-size: 11.5px; }
  .article-actions { gap: 20px; }
  .app-header { padding: 26px 48px 0; gap: 28px; }
  .header-actions { gap: 24px; }
  .missed-strip { padding: 16px 20px; }
}

.filter-field {
  margin-left: auto;
  max-width: 280px;
  width: 100%;
  padding: 9px 0;
  border: 0;
  border-bottom: 1px solid var(--color-hairline);
  background: none;
  font: inherit;
  font-size: 13px;
  color: var(--color-ink);
}
.filter-field::placeholder { color: var(--color-ink-muted); }

/* Hover is desktop-only and never a background fill. */
@media (hover: hover) {
  .header-action:hover { color: var(--color-ink); }
  .article-actions .action:hover { color: var(--color-ink); }
  .article-title:hover { text-decoration: underline; }
}
```

Add a desktop-only `Open` action as the first child of `.article-actions` (an `<a href={article.url} target="_blank" rel="noopener noreferrer" className="action">Open</a>`), hidden below 900px with `.article-actions .action-open { display: none; }` and shown inside the `min-width: 900px` block.

Add one plain-text topic after `.meta-dupes`, desktop only:

```tsx
{article.topics[0] && <><span className="meta-dot">·</span><span className="meta-tag">{article.topics[0]}</span></>}
```

with `.meta-tag { display: none; }` at base and `display: inline;` inside the media query.

- [ ] **Step 4: Run to verify passing**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=desktop -g "desktop layout"`
Expected: 3 passed.

- [ ] **Step 5: Confirm the collapse still works on a phone**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone`
Expected: all pass — thumbnail back to 76 × 76, gap back to 34px.

- [ ] **Step 6: Full suite, then commit**

```bash
git add web/src/App.css web/src/components/ArticleCard.tsx web/e2e/redesign.spec.ts
git commit -m "feat: desktop reading measure, underline filter, responsive collapse"
```

---

### Task 8: Drawer → three groups

**Model:** `opus`

Five labelled sections (FEEDS / SAVED / SETTINGS / YOU / ADMIN) become three unlabelled groups plus a settings block. All-caps section headers are removed entirely.

**Files:**
- Modify: `web/src/App.tsx` (the `<aside>` block, currently around lines 379–430)
- Modify: `web/src/components/Sidebar.tsx`
- Modify: `web/src/App.css`
- Modify: `web/e2e/redesign.spec.ts`

**Interfaces:**
- Consumes: tokens `--color-indent-active`, `--color-indent-inactive`, `--color-divider`, `--font-serif`.
- Produces: `.drawer-head` (wordmark + `"<username> · <N> unread"`); `.drawer-group` × 3; `.drawer-settings`; `.drawer-footer` with `Admin` (admin only), `Shortcuts`, `Sign out`.

**Group contents, exactly:**
1. `All feeds` with gold count; feed children indented 16px behind a 2px left rule.
2. `Saved articles`, `Hidden` (muted count), `Your stats`.
3. Settings block: `Photos`, `Compact`, `Sort`, `Theme` (Task 9 supplies the controls).

- [ ] **Step 1: Write the failing test**

```ts
test.describe('drawer', () => {
  test('has no all-caps section headers', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    await expect(page.locator('.sidebar-section-title')).toHaveCount(0);
  });

  test('names the reader and their unread count under the wordmark', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    await expect(page.locator('.drawer-head')).toContainText('Better News');
    await expect(page.locator('.drawer-sub')).toContainText('unread');
  });

  test('hides Admin from a plain reader', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    // fixtures' ME is a plain user unless mockAdmin is used.
    await expect(page.locator('.drawer-footer').getByText('Admin')).toHaveCount(0);
    await expect(page.locator('.drawer-footer').getByText('Sign out')).toBeVisible();
  });
});
```

Add `openDrawer` to the import at the top of the file.

- [ ] **Step 2: Run to verify failure**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "drawer"`
Expected: FAIL — `.sidebar-section-title` still resolves 5 elements.

- [ ] **Step 3: Implement**

In `App.tsx`, delete all five `<h2 className="sidebar-section-title">` elements and restructure the `<aside>` into `.drawer-head`, three `.drawer-group` divs, a `.drawer-settings` block and a `.drawer-footer`. Keep every existing handler — `setFeed`, `setSaved`, `setHidden`, `onManageFeeds`, sign-out — wired to the same controls; this task moves and restyles them, it does not change what they do. `Admin` in the footer renders only when `me?.role === 'admin'`, matching the current gating of `onManageFeeds`.

```css
.drawer-head { padding: 56px 28px 40px; }
.drawer-wordmark { font-family: var(--font-serif); font-size: 24px; font-weight: 600; line-height: 1.1; letter-spacing: -0.4px; color: var(--color-ink); }
.drawer-sub { margin-top: 8px; font-size: 12px; font-weight: 400; color: var(--color-ink-muted); }

.drawer-groups { display: flex; flex-direction: column; gap: 34px; padding: 0 28px; }
.drawer-group { display: flex; flex-direction: column; gap: 18px; }
.drawer-item { display: flex; align-items: center; justify-content: space-between; background: none; border: 0; padding: 0; font: inherit; color: var(--color-ink-secondary); font-size: 15px; cursor: pointer; }
.drawer-item.is-all { font-size: 17px; font-weight: 600; color: var(--color-ink); }
.drawer-item .count { color: var(--color-ink-meta); }
.drawer-item.is-all .count { color: var(--color-accent); }

.drawer-children { display: flex; flex-direction: column; gap: 18px; padding-left: 16px; border-left: 2px solid var(--color-indent-inactive); }
.drawer-children.is-active { border-left-color: var(--color-indent-active); }

.drawer-divider { height: 1px; background: var(--color-divider); margin: 0 28px; }
.drawer-footer { display: flex; gap: 24px; padding: 24px 28px 44px; font-size: 13px; color: var(--color-ink-muted); }

/* Desktop: the same drawer becomes a permanent 262px sidebar (handoff D). */
@media (min-width: 900px) {
  .sidebar {
    width: 262px;
    flex: none;
    background: var(--color-surface);
    padding: 30px 26px 26px;
    display: flex;
    flex-direction: column;
    gap: 34px;
    transform: none;
  }
  .drawer-head { padding: 0; }
  .drawer-wordmark { font-size: 19px; }
  .drawer-groups { padding: 0; gap: 34px; }
  .drawer-item { font-size: 14px; }
  .drawer-item.is-all { font-size: 15px; }
  .drawer-children { padding-left: 14px; }
  .drawer-divider { margin: 0; }
  .drawer-footer { margin-top: auto; padding: 0; font-size: 12px; }
}
```

The `.sidebar` selector must match whatever `App.tsx` already puts on the `<aside>`; if the overlay drawer uses a transform to slide in, the desktop rule above must reset it (`transform: none`) or the permanent sidebar renders off-screen.

- [ ] **Step 4: Run to verify passing**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "drawer"`
Expected: 3 passed.

- [ ] **Step 5: Run the design-system contract**

Run: `node ./node_modules/.bin/playwright test design-system.spec.ts`
Expected: PASS. It asserts every action has a visible control and that a plain reader sees no admin ones — removing section headers must not remove a control. If a control lost its only entry point, re-add it to the correct group.

- [ ] **Step 6: Full suite, then commit**

```bash
git add web/src/App.tsx web/src/components/Sidebar.tsx web/src/App.css web/e2e/redesign.spec.ts
git commit -m "feat: drawer collapses to three groups and a settings block"
```

---

### Task 9: Toggles and segmented controls

**Model:** `sonnet`

**Files:**
- Create: `web/src/components/Toggle.tsx`
- Create: `web/src/components/Segmented.tsx`
- Modify: `web/src/App.tsx` (settings block from Task 8)
- Modify: `web/src/App.css`
- Modify: `web/e2e/redesign.spec.ts`

**Interfaces:**
- Consumes: `.drawer-settings` from Task 8; tokens `--color-toggle-off`, `--color-track-2`, `--color-segment-selected`, `--color-accent`, `--radius-pill`.
- Produces:
  - `Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void })` — renders `<button role="switch" aria-checked>` with class `.toggle`.
  - `Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: readonly { value: T; label: string }[]; onChange: (v: T) => void })` — renders `<div role="radiogroup">` with class `.segmented`, each option a `<button role="radio" aria-checked>`.
- Wiring: `Photos` → `setPhotos` (`photos.ts`), `Compact` → `setDensity` (`density.ts`), `Sort` → the existing sort state (`score` | `date`), `Theme` → `setTheme` (`theme.ts`, `auto` | `light` | `dark`).

- [ ] **Step 1: Write the failing test**

```ts
test.describe('drawer controls', () => {
  test('Photos is a switch that reports its state', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    const sw = page.getByRole('switch', { name: 'Photos' });
    const before = await sw.getAttribute('aria-checked');
    await sw.click();
    await expect(sw).toHaveAttribute('aria-checked', before === 'true' ? 'false' : 'true');
  });

  test('Sort offers exactly Score and Date', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    const group = page.getByRole('radiogroup', { name: 'Sort' });
    await expect(group.getByRole('radio')).toHaveText(['Score', 'Date']);
  });

  test('Theme offers Auto, Light and Dark', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    const group = page.getByRole('radiogroup', { name: 'Theme' });
    await expect(group.getByRole('radio')).toHaveText(['Auto', 'Light', 'Dark']);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "drawer controls"`
Expected: FAIL — no `switch` or `radiogroup` roles exist.

- [ ] **Step 3: Write `Toggle.tsx`**

```tsx
/**
 * A switch, not a checkbox. `role="switch"` is what makes the state readable
 * to a screen reader and to a test -- the visual is a track and a knob, which
 * on their own say nothing.
 */
export function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="setting-row">
      <span className="setting-label">{label}</span>
      <button
        className="toggle"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
      >
        <span className="toggle-knob" />
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Write `Segmented.tsx`**

```tsx
/**
 * Two- and three-up segmented controls. A radiogroup rather than a set of
 * buttons: exactly one option is selected at a time, and that is what
 * `role="radio"` + `aria-checked` says.
 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="setting-row">
      <span className="setting-label">{label}</span>
      <div className="segmented" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o.value}
            className="segment"
            role="radio"
            aria-checked={value === o.value}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Wire them into the settings block**

In `App.tsx`, inside `.drawer-settings`:

```tsx
<Toggle label="Photos" checked={photos === 'on'} onChange={(v) => setPhotos(v ? 'on' : 'off')} />
<Toggle label="Compact" checked={density === 'compact'} onChange={(v) => setDensity(v ? 'compact' : 'comfortable')} />
<Segmented label="Sort" value={sort} options={[{ value: 'score', label: 'Score' }, { value: 'date', label: 'Date' }]} onChange={setSort} />
<Segmented label="Theme" value={theme} options={[{ value: 'system', label: 'Auto' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]} onChange={setTheme} />
```

The literal values are fixed and verified against the modules: `Photos = 'on' | 'off'`, `Density = 'comfortable' | 'compact'`, `ThemePreference = 'light' | 'dark' | 'system'`, sort = `'date' | 'score'`. **There is no `auto` theme value** — the automatic option is spelled `system` in `theme.ts` and `Auto` is only its visible label.

- [ ] **Step 6: Add the styles**

```css
.drawer-settings { display: flex; flex-direction: column; gap: 22px; padding: 0 28px; }
.setting-row { display: flex; align-items: center; justify-content: space-between; }
.setting-label { font-size: 15px; color: var(--color-ink-secondary); }

.toggle {
  width: 42px; height: 26px; flex: none;
  border: 0; padding: 0 3px;
  border-radius: var(--radius-pill);
  background: var(--color-toggle-off);
  display: flex; align-items: center; cursor: pointer;
}
.toggle[aria-checked='true'] { background: var(--color-accent); justify-content: flex-end; }
.toggle-knob { width: 20px; height: 20px; border-radius: var(--radius-pill); background: var(--color-segment-selected); }

.segmented { display: flex; gap: 0; padding: 3px; border-radius: var(--radius-pill); background: var(--color-track-2); }
.segment {
  border: 0; background: none; padding: 4px 10px;
  border-radius: var(--radius-pill);
  font: inherit; font-size: 12px; font-weight: 400;
  color: var(--color-ink-muted); cursor: pointer;
}
.segment[aria-checked='true'] { background: var(--color-segment-selected); color: var(--color-ink); font-weight: 600; }

@media (min-width: 900px) {
  .drawer-settings { gap: 19px; }
  .toggle { width: 38px; height: 23px; }
  .toggle-knob { width: 17px; height: 17px; }
  .segment { font-size: 11.5px; }
}
```

- [ ] **Step 7: Run to verify passing, then commit**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "drawer controls"`
Expected: 3 passed. Then run the full suite.

```bash
git add web/src/components/Toggle.tsx web/src/components/Segmented.tsx web/src/App.tsx web/src/App.css web/e2e/redesign.spec.ts
git commit -m "feat: drawer toggles and segmented sort and theme controls"
```

---

### Task 10: Sign in restyle

**Model:** `sonnet`

**Username is kept.** No "Forgot?", no magic link, no email — see Global Constraints.

**Files:**
- Modify: `web/src/screens/SignIn.tsx`
- Modify: `web/src/App.css`
- Modify: `web/e2e/redesign.spec.ts`

**Interfaces:**
- Consumes: `--font-serif`, `--color-field-underline`, `--color-ink-faint`, `--color-accent`, `--color-on-accent`, `--color-danger`.
- Produces: `.signin` with `.signin-wordmark`, `.signin-tagline` ("Your feeds, ranked and quiet."), `.field` × 2 with `.field-label`, and `.signin-cta`.
- **Preserves** the transport-error handling added on 2026-09-01: `isNetworkError(err)` renders "Could not reach the server. Check your connection, then try again." rather than the engine's raw message. Do not drop this.

- [ ] **Step 1: Write the failing test**

```ts
test.describe('sign in', () => {
  test('asks for a username, not an email, and offers no magic link', async ({ page }) => {
    await signInFlow(page);
    await page.goto('/');
    await expect(page.locator('.field-label').first()).toHaveText('Username');
    await expect(page.getByText(/magic link/i)).toHaveCount(0);
    await expect(page.getByText(/forgot/i)).toHaveCount(0);
  });

  test('the CTA is pinned to the bottom on a phone', async ({ page }) => {
    await signInFlow(page);
    await page.goto('/');
    const cta = await page.locator('.signin-cta').boundingBox();
    const vp = page.viewportSize()!;
    // Bottom-weighted so the iOS keyboard never covers it.
    expect(cta!.y).toBeGreaterThan(vp.height * 0.6);
  });
});
```

Add `signInFlow` to the imports.

- [ ] **Step 2: Run to verify failure**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "sign in"`
Expected: FAIL — `.field-label` does not exist.

- [ ] **Step 3: Implement**

Restructure the returned form as wordmark block → fields → pinned CTA, keeping `submit`, `busy`, and the existing `catch` intact:

```tsx
<form className="signin" onSubmit={submit}>
  <div className="signin-head">
    <h1 className="signin-wordmark">Better News</h1>
    <p className="signin-tagline">Your feeds, ranked and quiet.</p>
  </div>

  <div className="signin-fields">
    <label className="field">
      <span className="field-label">Username</span>
      <input name="username" value={username} onChange={(e) => setUsername(e.target.value)}
        autoComplete="username" autoFocus required />
    </label>
    <label className="field">
      <span className="field-label">Password</span>
      <input name="password" type="password" value={password}
        onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
    </label>
    {error && <p className="field-error">{error}</p>}
  </div>

  <div className="signin-cta">
    <button type="submit" disabled={busy || !username.trim() || !password}>
      {busy ? 'Signing in…' : 'Sign in'}
    </button>
  </div>
</form>
```

```css
.signin { display: flex; flex-direction: column; min-height: 100%; padding: 0 28px; max-width: none; margin: 0; }
.signin-head { padding-top: 150px; }
.signin-wordmark { margin: 0; font-family: var(--font-serif); font-size: 30px; font-weight: 600; letter-spacing: -0.5px; color: var(--color-ink); }
.signin-tagline { margin: 10px 0 0; font-size: 15px; line-height: 1.5; color: var(--color-ink-muted); }

.signin-fields { margin-top: 64px; display: flex; flex-direction: column; gap: 30px; }
.field { display: flex; flex-direction: column; gap: 9px; }
.field-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--color-ink-faint); }
.field input {
  border: 0; border-bottom: 1px solid var(--color-field-underline);
  background: none; padding: 0 0 13px; font: inherit; font-size: 17px; color: var(--color-ink);
}
.field-error { margin: 0; font-size: 12px; color: var(--color-danger); }

.signin-cta { margin-top: auto; padding-bottom: 44px; display: flex; flex-direction: column; gap: 16px; }
.signin-cta button {
  height: 52px; border: 0; border-radius: var(--radius-pill);
  background: var(--color-accent); color: var(--color-on-accent);
  font: inherit; font-size: 15px; font-weight: 600; cursor: pointer;
}

@media (min-width: 900px) {
  .signin { max-width: 352px; margin: 0 auto; justify-content: center; padding: 0; }
  .signin-head { padding-top: 0; }
  .signin-wordmark { font-size: 26px; }
  .signin-tagline { font-size: 13px; }
  .signin-fields { margin-top: 34px; gap: 26px; }
  .field input { font-size: 15px; padding-bottom: 11px; }
  .signin-cta { margin-top: 34px; padding-bottom: 0; }
  .signin-cta button { height: 46px; font-size: 14px; }
}
```

- [ ] **Step 4: Run to verify passing**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "sign in"`
Expected: 2 passed.

- [ ] **Step 5: Confirm the transport-error message survived**

Run: `node ./node_modules/.bin/playwright test auth.spec.ts`
Expected: PASS. Then confirm by inspection that `isNetworkError` is still imported and used in the `catch`.

- [ ] **Step 6: Full suite, then commit**

```bash
git add web/src/screens/SignIn.tsx web/src/App.css web/e2e/redesign.spec.ts
git commit -m "feat: restyle sign in, keeping username and password"
```

---

### Task 11: Single-story mode *(optional — confirm before dispatching)*

**Model:** `opus`

A **new feature**, not a restyle: the handoff calls it "an optional alternative to the list". Skip this task unless it is explicitly wanted.

**Files:**
- Create: `web/src/components/SingleStory.tsx`
- Modify: `web/src/App.tsx` (mode state + entry point)
- Modify: `web/src/App.css`
- Modify: `web/e2e/redesign.spec.ts`

**Interfaces:**
- Consumes: `useSwipe` from `web/src/useSwipe.ts`; tokens `--color-shell-story`, `--color-surface-story`, `--color-gold-pill-surface`, `--color-gold-pill-ink`, `--radius-story`.
- Produces: `SingleStory({ articles, index, onAdvance, onVote, onOpen }: { articles: Article[]; index: number; onAdvance: (n: number) => void; onVote: (a: Article, v: 1 | -1) => void; onOpen: (a: Article) => void })`; DOM `.single-story` with `.single-counter` (`"<n> OF <total>"`), `.single-card`, `.single-actions`.

Behaviour: swipe left = Down, swipe right = Up; both animate the card off-screen over 250ms `cubic-bezier(.2,.8,.2,1)` and advance the counter. Tapping the card opens the article. The score pill is retained **here only** — `padding: 4px 8px`, `border-radius: var(--radius-pill)`, `background: var(--color-gold-pill-surface)`, `color: var(--color-gold-pill-ink)`.

- [ ] **Step 1: Write the failing test**

```ts
test.describe('single story', () => {
  test('counts the position in the list', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.getByRole('button', { name: 'One at a time' }).click();
    await expect(page.locator('.single-counter')).toHaveText(/^1 OF \d+$/);
  });

  test('the score pill survives here and nowhere else', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.getByRole('button', { name: 'One at a time' }).click();
    await expect(page.locator('.single-card .score-pill')).toBeVisible();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `node ./node_modules/.bin/playwright test redesign.spec.ts --project=phone -g "single story"`
Expected: FAIL — no "One at a time" control.

**Status: DONE.** This task was built and shipped; `SingleStory.tsx` renders a centred card capped at 420px on mobile and centred above 900px, holds the score pill (the only place it appears in the redesign), and advances through the list via swipe-left/-right gestures. Commit: `25bda5a Add single-story reading mode`.

A subsequent follow-up (`89be0e0 Cap single-story at desktop width instead of letting it stretch`) had to constrain the component — without the cap it stretched to 955px, putting a 27px serif headline over an unreadable measure — so the override sits at the end of `App.css` on purpose, where specificity lets the max-width win.

---

### Task 12: Full verification pass

**Model:** `opus`

**Files:**
- Modify: `CLAUDE.md` (the Frontend section)

- [ ] **Step 1: Run every suite that can run**

```bash
cd web && node ./node_modules/.bin/playwright test
node ./node_modules/.bin/tsc --noEmit -p tsconfig.app.json
node ./node_modules/.bin/tsc --noEmit -p tsconfig.e2e.json
node ./node_modules/.bin/vite build
cd ../mobile && node ./node_modules/.bin/jest
```

Expected: all green. The build matters independently — typecheck does not bundle and never touches the CSS minifier, which is how invalid CSS once shipped with three green checks.

- [ ] **Step 2: Check both themes render**

Run: `node ./node_modules/.bin/playwright test --project=safari`
Expected: PASS. WebKit is not optional here — it is the engine the reader actually uses, and it has already found three genuine bugs in this app.

- [ ] **Step 3: Update `CLAUDE.md`**

Rewrite the Frontend bullets that describe the old card ("The article card is three rows, in block flow", the four-column grid history, the tag cap) to describe the redesign: two rows, one combined meta+actions line, no tints, 760px desktop measure, three drawer groups. Record why the score pill survives only in single-story mode, and that Source Serif 4 is self-hosted rather than linked.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: describe the whitespace redesign in the codebase guide"
```

---

## Decisions Made — 2026-09-01

1. **Task 11** was confirmed wanted and built. Single-story mode ships as an alternative to the list, reached from the drawer as "One at a time", advancing via swipe gestures and holding the score pill (the only place it renders in the redesign).

2. **"Mark all read" vs "Dismiss all"** — both labels wire to `POST /articles/dismiss-all`. The reader chose to keep both phrasings at every width rather than unifying the label, trading consistency for clarity in context (one reads as "I'll come back" on a phone, the other as "gone" on desktop). Both call the same endpoint.

3. **The undo affordance** — still not built. The handoff calls for "confirm via undo affordance, not a dialog", but dismissal is not reversible in bulk. Considered and deferred; dismissed articles can be read from `?dismissed=1` and the operation is not irreversible at the row level (`swipe-left` leaves a undo trail in the UI). Raise if a time-window undo is wanted.

---

## Follow-ups and Surprises

**Five tasks shipped after the planned twelve:**

1. **Topic filter** (`f8d562e`) — `.meta-tag` became clickable to filter the list to that topic.
2. **Digest metadata endpoint** (`5a2f855`) — `GET /digest/meta` returns story count and estimated read time without generating the briefing, backing the strip without an LLM call on every page load.
3. **Drawer extraction** (`1137298`) — `Drawer.tsx` was pulled out of a 751-line `App.tsx` (608 remaining) as a standalone component.
4. **Visual coverage** (`8edb366`) — Screenshot tests over the four redesigned surfaces caught defects the regular suite missed: an invisible keyboard focus row, `--font-ui` never applying, a forced-password screen losing its styling when a sibling was restyled, and a single-story card stretching past its measure.
5. **Dead-CSS sweep** (`89d65ef`) — Removed pill styling from count badges and deleted unused tokens from the palette.

**Two briefs specified something that already existed:**

- **A header stacked above the old toolbar** — Task 6 (Mobile header) created a new header but didn't remove the existing toolbar, so they rendered together until Task 7's follow-up (`2f7267d`) unified them. The old icon row is gone; the header carries all actions as text.
- **A filter field that was nearly built twice** — Task 7 restyled the existing `#search` field as an underline input rather than creating a new `.filter-field`. The test comment in the diff reads: "It is not a new `.filter-field`: the app has had that field all along, and adding a second one is exactly the mistake the previous task had to be rescued from."

**The environment assumptions were incomplete:**

- The plan assumed a working `npm` on the machine. Task 1 had to install Node from source — the VS Code server ships a `node` binary but no `npm`, and there is no npm anywhere on the image.

These gaps point toward a tighter planning process: confirm the build environment before writing steps, and require briefs to include a sentence on what already exists in the codebase so duplicating work surfaces as a mismatch.

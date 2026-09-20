import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import type { Article } from '../../shared/api';
import { ARTICLES, article, mockAdmin, mockApi, openDrawer, signedIn } from './fixtures';

// WCAG relative luminance / contrast ratio, computed from a browser's
// `rgb(...)` / `rgba(...)` computed-style strings.
function relativeLuminance(rgb: string): number {
  const [r, g, b] = (rgb.match(/[\d.]+/g) ?? []).map(Number).map((c) => c / 255);
  const linear = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrastRatio(a: string, b: string): number {
  const [lighter, darker] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (lighter + 0.05) / (darker + 0.05);
}

// ── the token discipline ──────────────────────────────────────────────────────

test('App.css names tokens and never a hex value', () => {
  // Not style policing: #d14343 appeared 13 times before this, and every one
  // was a colour that could not follow the theme. A token can; a literal
  // cannot. Adding a colour means adding a token in index.css.
  const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8');
  const hex = css.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [];
  expect(hex, `hex literals in App.css: ${hex.join(', ')}`).toEqual([]);
});

test('every token App.css uses is actually defined', () => {
  // A typo in a var() name is silent -- the property just does not apply, and
  // the element renders with an inherited or default colour that usually looks
  // plausible. Nothing else in the stack catches that.
  const base = new URL('../src/', import.meta.url);
  const app = readFileSync(new URL('App.css', base), 'utf8');
  const tokens = readFileSync(new URL('index.css', base), 'utf8');
  const defined = new Set(tokens.match(/--[a-z0-9-]+(?=\s*:)/g) ?? []);
  const used = new Set(
    (app.match(/var\(\s*(--[a-z0-9-]+)/g) ?? []).map((m) => m.replace(/var\(\s*/, '')),
  );
  const missing = [...used].filter((t) => !defined.has(t));
  expect(missing, `undefined tokens: ${missing.join(', ')}`).toEqual([]);
});

test('radii come from the scale', () => {
  const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8');
  // 999px is a pill, not a scale value, and is exempt on purpose.
  const literals = (css.match(/border-radius:\s*\d+px/g) ?? [])
    .filter((r) => !r.includes('999'));
  expect(literals).toEqual([]);
});

// ── the modal contract ────────────────────────────────────────────────────────

const MODALS = [
  { command: 'server settings', selector: '.settings-screen', label: 'Settings' },
  { command: 'manage feeds', selector: '.manage-feeds', label: 'Feeds' },
  { command: 'manage users', selector: '.admin-users', label: 'Users' },
  { command: 'your stats', selector: '.insights-screen', label: 'Insights' },
  { command: 'ollama log', selector: '.call-log', label: 'Ollama log' },
  { command: 'profile', selector: '.profile-screen', label: 'Your profile' },
];

test.describe('every modal', () => {
  test.beforeEach(async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');
  });

  for (const { command, selector, label } of MODALS) {
    test(`${label} announces itself and traps focus`, async ({ page }) => {
      await page.keyboard.press('Control+k');
      await page.locator('.command-palette input').fill(command);
      await page.locator('.command-item').first().click();
      const dialog = page.locator(selector);
      await expect(dialog).toBeVisible();

      // The old server-rendered reader was a native <dialog aria-modal="true">.
      // The SPA replaced it with a bare div and lost all of this.
      await expect(dialog).toHaveAttribute('role', 'dialog');
      await expect(dialog).toHaveAttribute('aria-modal', 'true');
      await expect(dialog).toHaveAttribute('aria-label', label);

      // Tab a long way and never escape the dialog.
      for (let i = 0; i < 25; i++) await page.keyboard.press('Tab');
      const inside = await dialog.evaluate((el) => el.contains(document.activeElement));
      expect(inside, 'focus walked out of the dialog').toBe(true);

      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
    });
  }
});

test('closing a modal returns focus to what opened it', async ({ page }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');

  // A keyboard user who closes a dialog should not be dumped at the top of the
  // document with their place in the page lost.
  // `.sidebar-item` was the labelled sections' row class and went with them;
  // the drawer's footer links are the same kind of opener, so this holds the
  // same claim against the shape that replaced it.
  const opener = page.locator('.drawer-footer button').first();
  await opener.focus();
  const before = await page.evaluate(() => document.activeElement?.className ?? '');
  await page.keyboard.press('Control+k');
  await expect(page.locator('.command-palette')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.command-palette')).toHaveCount(0);
  const after = await page.evaluate(() => document.activeElement?.className ?? '');
  expect(after).toBe(before);
});

// ── every action has a visible control ────────────────────────────────────────

test.describe('nothing is command-palette-only', () => {
  test.beforeEach(async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');
  });

  // Settings, Users, Insights, the Ollama log, Manage feeds and Sign out were
  // all reachable *only* through Ctrl-K, which put the app's whole admin
  // surface behind a shortcut you had to already know existed.
  // Named as the drawer names them: the admin section calls it "Server
  // settings" to distinguish it from the reader's own Settings section, which
  // holds density, sort and theme.
  const CONTROLS = ['Server settings', 'Users', 'Your stats', 'Ollama log',
                    'Manage feeds', 'Sign out', 'Keyboard shortcuts'];

  for (const name of CONTROLS) {
    test(`an admin can click "${name}" without the palette`, async ({ page }) => {
      await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
    });
  }

  test('a plain reader sees the reader controls and none of the admin ones', async ({ page }) => {
    await page.route('**/api/v1/me', (r) => r.fulfill({
      json: { id: 2, username: 'plain', role: 'user', must_change_password: false,
              declickbait: false, content_filter_mode: 'off' },
    }));
    await page.reload();
    await page.waitForSelector('.article-row');
    for (const name of ['Settings', 'Users', 'Insights', 'Ollama log', 'Manage feeds']) {
      await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
    }
    // Still theirs to reach: their own account and the way out. The profile
    // button is named for the reader, so its accessible name is the username.
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'plain' })).toBeVisible();
  });

  test('every icon-only control has an accessible name', async ({ page }) => {
    // An icon with no name is a mystery to a screen reader and to a tooltip.
    // The whole drawer, not one section of it: `.sidebar-section` is gone, and
    // scoping to a class that no longer exists would have made this pass by
    // matching nothing at all.
    const total = await page.locator('.sidebar button, .sidebar-manage').count();
    expect(total, 'no drawer controls found -- this test is asserting nothing')
      .toBeGreaterThan(0);
    const nameless = await page.locator('.sidebar button, .sidebar-manage')
      .evaluateAll((els) => els
        .filter((el) => !el.textContent?.trim() && !el.getAttribute('aria-label'))
        .length);
    expect(nameless).toBe(0);
  });
});

// ── controls and metrics ──────────────────────────────────────────────────────

test.describe('the shared pill', () => {
  test.beforeEach(async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');
  });

  test('the unread count is plain text, not a pill', async ({ page }) => {
    // It carried `.pill` while the card had pills to match. Nothing rendered
    // that border or that radius, so the shape was decoration on a number.
    const el = page.locator('.sidebar-feed-count').first();
    await expect(el).toHaveCount(1);
    const style = await el.evaluate((n) => {
      const cs = getComputedStyle(n);
      return { radius: cs.borderTopLeftRadius, border: cs.borderTopWidth };
    });
    expect(style.radius).toBe('0px');
    expect(style.border).toBe('0px');
  });

  test('no ad-hoc pill radii survive in App.css', () => {
    const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8');
    expect(css).not.toContain('999px');
  });
});

// ── the offline bar ───────────────────────────────────────────────────────────

test('the offline bar is readable in dark mode', async ({ page, context }) => {
  // .offline-bar's text used --color-on-accent -- text for the *gold accent*,
  // not this bar. In dark mode that is #1a1509, near-black, on
  // --color-offline-surface's dark amber (#5a4310): 1.94:1, against WCAG AA's
  // 4.5:1 for normal text. --color-offline-ink exists for exactly this and
  // gets 8.29:1. Drive it the way pwa.spec's offline test does: `watchConnectivity`
  // reads `navigator.onLine`, not the event, so the context must actually go
  // offline before the event fires.
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
  await openDrawer(page);
  await page.getByRole('radiogroup', { name: 'Theme' }).getByRole('radio', { name: 'Dark' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

  await context.setOffline(true);
  await page.evaluate(() => window.dispatchEvent(new Event('offline')));
  const bar = page.locator('.offline-bar');
  await expect(bar).toBeVisible();

  const { color, background } = await bar.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { color: cs.color, background: cs.backgroundColor };
  });
  expect(contrastRatio(color, background), `text ${color} on background ${background}`)
    .toBeGreaterThanOrEqual(4.5);
});

test('sort is a segmented control defaulting to Date', async ({ page }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');

  // It lives in the drawer's Settings section now, not the top bar. Task 9
  // replaced the ambiguous Date<->Score switch with a 2-up radiogroup: Date
  // and Score are two positions, not an on/off state.
  await openDrawer(page);
  const group = page.getByRole('radiogroup', { name: 'Sort' });
  await expect(group).toBeVisible();
  const date = group.getByRole('radio', { name: 'Date' });
  const score = group.getByRole('radio', { name: 'Score' });
  await expect(date).toHaveAttribute('aria-checked', 'true');
  await expect(score).toHaveAttribute('aria-checked', 'false');

  const sorted = page.waitForRequest((r) => r.url().includes('sort=score'));
  await score.click();
  await sorted;
  await expect(score).toHaveAttribute('aria-checked', 'true');
  await expect(date).toHaveAttribute('aria-checked', 'false');
});

test('theme is three icons, and the current one is marked', async ({ page }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
  // The theme picker lives in the sidebar, which is off-screen on a phone.
  await openDrawer(page);

  const group = page.getByRole('radiogroup', { name: 'Theme' });
  await expect(group.getByRole('radio')).toHaveCount(3);
  // A dropdown made a three-state preference cost a menu to change.
  await expect(page.locator('select#theme-select')).toHaveCount(0);

  const dark = group.getByRole('radio', { name: 'Dark' });
  await dark.click();
  await expect(dark).toHaveAttribute('aria-checked', 'true');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('on a phone the list is not flush against the screen edge', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'phone only');
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
  // It started at exactly 0: the thumbnail and score badge sat on the glass.
  const x = await page.evaluate(() =>
    document.querySelector('.article-row')!.getBoundingClientRect().x);
  expect(x).toBeGreaterThanOrEqual(8);
});

test('on a desktop the card is two rows, not columns', async ({ page, isMobile }) => {
  test.skip(isMobile, 'desktop only');
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');

  // Two rows now, not three: the story, then one line carrying the facts a
  // reader reads and the buttons they press. That line is the thing to hold --
  // it collapsed four separate rows into one, and it must not wrap back out.
  const meta = (await page.locator('.article-row .article-meta').first().boundingBox())!;
  expect(meta.height, 'the meta row wrapped').toBeLessThan(48);

  // And the rows are in order, not overlapping.
  const head = (await page.locator('.article-row .article-head').first().boundingBox())!;
  expect(head.y).toBeLessThan(meta.y);
  expect(head.y + head.height).toBeLessThanOrEqual(meta.y + 1);
});


/**
 * The drawer.
 *
 * It was five all-caps labelled sections -- FEEDS / SAVED / SETTINGS / YOU /
 * ADMIN -- and is three unlabelled groups, a settings block and a footer. Two
 * of the three tests here described the labels themselves and one described a
 * claim that outlived them; see the note on each. The *shape* is asserted in
 * redesign.spec's `drawer` block. What stays here is the contract this file is
 * for: a control for every action, and none of the admin ones for a reader.
 */
test.describe('the drawer', () => {
  test.beforeEach(async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await mockAdmin(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');
    await openDrawer(page);
  });

  // Deleted with the labels: "in the order a reader reaches for them" asserted
  // `.sidebar-section-title` read exactly Feeds / Saved / Settings / You /
  // Admin. The redesign removes the headers entirely, so its subject is gone
  // rather than moved. redesign.spec asserts the count is now zero.

  test('the display preferences are all in the drawer, not the header', async ({ page }) => {
    // Density and sort were in the top bar, where on a 390px screen they cost
    // a whole row of a header that was already a quarter of the viewport.
    // The section that held them is gone; the block that replaced it is
    // `.drawer-settings`, and the claim -- these belong here and nowhere else
    // -- is unchanged. Photos is asserted too: it is in the same block and was
    // simply missing from the list before.
    const settings = page.locator('.drawer-settings');
    await expect(settings.getByRole('switch', { name: 'Show photos' })).toBeVisible();
    await expect(settings.getByRole('switch', { name: 'Compact list' })).toBeVisible();
    await expect(settings.getByRole('radiogroup', { name: 'Sort' })).toBeVisible();
    await expect(settings.getByRole('radiogroup', { name: 'Theme' })).toBeVisible();

    // And gone from the top bar, or they would be in two places at once.
    // `.app-header`, not the `.site-header` wrapper that used to hold it: that
    // class is gone, and a locator matching nothing would satisfy
    // `toHaveCount(0)` no matter where the switches ended up.
    await expect(page.locator('.app-header')).toHaveCount(1);
    await expect(page.locator('.app-header').getByRole('switch')).toHaveCount(0);
  });

  test('a plain reader gets the drawer without the admin links', async ({ page }) => {
    // Was "a plain reader gets four sections and no Admin", counted off the
    // section headers. There are no sections to count now, so it asserts the
    // thing the count stood for: the admin screens have no entry point, and
    // everything that is theirs still does.
    await page.route('**/api/v1/me', (r) => r.fulfill({
      json: { id: 2, username: 'plain', role: 'user', must_change_password: false,
              declickbait: false, content_filter_mode: 'off' },
    }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await openDrawer(page);

    for (const name of ['Users', 'Server settings', 'Ollama log', 'Your stats',
                        'Manage feeds']) {
      await expect(page.locator('.sidebar').getByRole('button', { name, exact: true }))
        .toHaveCount(0);
    }
    // Their own account and the way out stay theirs, and so do the feeds, the
    // lists and every display preference.
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Keyboard shortcuts' })).toBeVisible();
    await expect(page.locator('.drawer-groups')).toContainText('All feeds');
    await expect(page.locator('.drawer-groups')).toContainText('Saved articles');
    await expect(page.locator('.drawer-groups')).toContainText('Hidden');
    await expect(page.getByRole('switch', { name: 'Compact list' })).toBeVisible();
  });
});

// ── contrast ──────────────────────────────────────────────────────────────────

/**
 * Every rendered text node clears WCAG AA, in both themes.
 *
 * Added after an audit found 16 classes below 4.5:1 in light and 15 in dark,
 * the worst at 2.12:1 -- the action buttons on every card. Two of them were
 * token mix-ups rather than palette choices: the offline bar coloured itself
 * with the *gold* accent's ink, and a cleanup swapped the what-you-missed
 * button's `--color-on-accent` for `--color-offline-ink`, putting near-white on
 * gold. Both are "light ink", which is why the swap read as harmless and why
 * nothing caught it -- the screenshots cannot see contrast, and no assertion
 * looked at colour at all.
 *
 * This measures rather than naming tokens, so it fails however the regression
 * arrives.
 */
/**
 * Every rendered text node's *effective* colour, composited the way the
 * browser paints it.
 *
 * Two things the first version of this measured wrong, and read state needed
 * both. It read the *declared* `color`, and it walked to a painting ancestor
 * while ignoring that ancestor's `opacity` -- it only skipped an element whose
 * *own* opacity was under 0.3. `.article-row.read` fades the row, not the
 * text, so a read headline at 2.19:1 was reported as the 5.10:1 its declared
 * colour would give on an opaque row. This composites the whole ancestor
 * chain instead: each painted background over the one behind it, every layer
 * dimmed by the cumulative `opacity` between it and the root, then the text
 * on top of that. `rgba()` backgrounds are layers rather than walls for the
 * same reason.
 */
const contrastProbe = () => {
  const lum = (c: number[]) => {
    const s = c.map((v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * s[0] + 0.7152 * s[1] + 0.0722 * s[2];
  };
  const parse = (v: string) => (v.match(/[\d.]+/g) || []).map(Number);
  const over = (fg: number[], bg: number[], a: number) => fg.map((v, i) => bg[i] + (v - bg[i]) * a);

  const out: {
    label: string; ratio: number; alpha: number;
    size: number; large: boolean; read: boolean;
  }[] = [];

  document.querySelectorAll('*').forEach((el) => {
    const hasText = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent?.trim());
    if (!hasText) return;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') return;
    // WCAG 1.4.3 exempts an inactive control, and `button:disabled` is faded
    // to 0.4 on purpose. Nothing else is skipped for being faint: being hard
    // to read is the thing this sweep is looking for.
    if ((el as HTMLButtonElement).disabled || el.getAttribute('aria-disabled') === 'true') return;

    const chain: Element[] = [];
    for (let n: Element | null = el; n; n = n.parentElement) chain.unshift(n);
    let bg = [255, 255, 255];
    let alpha = 1;
    for (const n of chain) {
      const ncs = getComputedStyle(n);
      alpha *= Number(ncs.opacity);
      const b = parse(ncs.backgroundColor);
      const ba = b.length > 3 ? b[3] : 1;
      if (b.length >= 3 && ba > 0) bg = over(b.slice(0, 3), bg, ba * alpha);
    }
    if (alpha === 0) return;
    const c = parse(cs.color);
    const fg = over(c.slice(0, 3), bg, (c.length > 3 ? c[3] : 1) * alpha);
    const [l1, l2] = [lum(fg), lum(bg)];
    const size = parseFloat(cs.fontSize);
    out.push({
      label: (el as HTMLElement).className?.toString().split(' ')[0] || el.tagName,
      ratio: (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05),
      alpha,
      size,
      large: size >= 24 || (size >= 18.66 && Number(cs.fontWeight) >= 700),
      read: !!el.closest('.article-row.read'),
    });
  });
  return out;
};

/**
 * A read row is deliberately recessive, so it is held to 3:1 rather than to
 * AA's 4.5 -- and held to it, not excused from it: `read state stays legible`
 * below owns that floor and the distance from unread, and the sweep reports
 * the number either way.
 */
const READ_FLOOR = 3;

/** The default fixture has no read article, so the state that needed
 *  measuring most was never on the page the sweep scanned. Mixed in here
 *  rather than in `ARTICLES` itself: visual.spec.ts's baselines are shot from
 *  that list, and a read first row would move all eight of them. */
const MIXED: Article[] = [
  article(1, { state: { read: true, saved: false, dismissed: false, opinion: null } }),
  ...ARTICLES.slice(1),
];

/**
 * Every rendered text node clears WCAG AA, in both themes.
 *
 * Added after an audit found 16 classes below 4.5:1 in light and 15 in dark,
 * the worst at 2.12:1 -- the action buttons on every card. Two of them were
 * token mix-ups rather than palette choices: the offline bar coloured itself
 * with the *gold* accent's ink, and a cleanup swapped the what-you-missed
 * button's `--color-on-accent` for `--color-offline-ink`, putting near-white on
 * gold. Both are "light ink", which is why the swap read as harmless and why
 * nothing caught it -- the screenshots cannot see contrast, and no assertion
 * looked at colour at all.
 *
 * This measures rather than naming tokens, so it fails however the regression
 * arrives.
 */
for (const theme of ['light', 'dark'] as const) {
  test(`text clears WCAG AA in ${theme}`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem('theme', t), theme);
    await signedIn(page);
    await mockApi(page, MIXED);
    await page.goto('/');
    await page.locator('.article-row').first().waitFor();
    await openDrawer(page);

    const measured = await page.evaluate(contrastProbe);
    expect(measured.some((m) => m.read), 'no read row was scanned').toBe(true);

    const failures = [...new Set(measured
      .filter((m) => {
        const need = m.read ? READ_FLOOR : (m.large ? 3 : 4.5);
        return m.ratio < need;
      })
      .map((m) => `${m.label} ${m.ratio.toFixed(2)}:1 `
        + `(needs ${m.read ? READ_FLOOR : (m.large ? 3 : 4.5)}, opacity ${m.alpha.toFixed(2)})`))];

    expect(failures, `below WCAG AA in ${theme}:\n  ${failures.join('\n  ')}`).toEqual([]);
  });
}

/**
 * Read state recedes without going under.
 *
 * The row is faded to 0.8 over a muted headline colour; it used to be 0.55,
 * with the summary compounding a second 0.7 on top, and it landed at 2.19:1
 * and 1.64:1 in light. That was survivable while the read rule also set
 * `font-weight: 500` against an unread 600 -- stroke weight was doing what the
 * fade had taken -- and the branch that brought the list to 15/400 removed the
 * weight and left the fade. Both halves are asserted: a floor, so read stays
 * readable, and a distance, so read never stops looking read.
 */
for (const theme of ['light', 'dark'] as const) {
  test(`read state stays legible and still reads as read in ${theme}`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem('theme', t), theme);
    await signedIn(page);
    await mockApi(page, MIXED);
    await page.goto('/');
    await page.locator('.article-row.read').first().waitFor();

    const measured = await page.evaluate(contrastProbe);
    const pick = (cls: string, read: boolean) => {
      const m = measured.find((x) => x.label === cls && x.read === read);
      expect(m, `no ${read ? 'read' : 'unread'} .${cls} on the page`).toBeTruthy();
      return m!.ratio;
    };

    const readTitle = pick('article-title', true);
    const readSummary = pick('article-summary', true);
    expect(readTitle, `read headline at ${readTitle.toFixed(2)}:1`).toBeGreaterThanOrEqual(READ_FLOOR);
    expect(readSummary, `read summary at ${readSummary.toFixed(2)}:1`).toBeGreaterThanOrEqual(READ_FLOOR);

    // ...and still unmistakably read: the unread headline is several times
    // the contrast of the read one. 2 is a floor, not the measurement -- it
    // lands near 5 -- and it is what stops "make read legible" from being
    // answered by making read look unread.
    const unreadTitle = pick('article-title', false);
    expect(unreadTitle / readTitle, `unread ${unreadTitle.toFixed(2)}:1 vs read ${readTitle.toFixed(2)}:1`)
      .toBeGreaterThan(2);
  });
}

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
  // Use CSS selectors for Saved and Hidden to avoid getByRole timing issues
  const saved = await type(page.locator('.sidebar-feed.is-lead').first());
  const hidden = await type(page.locator('.sidebar-feed.is-lead').nth(1));
  expect(saved, 'Saved does not match All feeds').toBe(all);
  expect(hidden, 'Hidden does not match All feeds').toBe(all);

  // ...and a feed underneath is still visibly subordinate.
  const feed = await type(page.locator('.sidebar-feed-nested').first());
  expect(feed, 'a feed row was promoted to the lead treatment').not.toBe(all);
});

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

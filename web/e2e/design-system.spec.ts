import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { mockAdmin, mockApi, openDrawer, signedIn } from './fixtures';

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
  // The footer tray is gone; the drawer is labelled sections now.
  const opener = page.locator('.sidebar-item').first();
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
    const nameless = await page.locator('.sidebar-section button, .sidebar-manage')
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

  test('every pill is the same height, on touch too', async ({ page, isMobile }) => {
    // Topic chips are buttons, and a blanket 40px touch target turned an 11px
    // inline chip into the tallest thing on the card. They were three separate
    // near-misses before this — three radii and three paddings.
    const heights = await page.evaluate(() => {
      const h = (s: string) => document.querySelector(s)?.getBoundingClientRect().height ?? null;
      return { chip: h('.topic-chip'), count: h('.sidebar-feed-count'), badge: h('.score-badge') };
    });
    expect(new Set(Object.values(heights)).size, JSON.stringify(heights)).toBe(1);
    // The size floor is a touch-target rule, so it only applies on a coarse
    // pointer -- 22px is right for a mouse and would be mean on a thumb.
    if (isMobile) {
      expect(heights.chip!).toBeGreaterThanOrEqual(24);   // WCAG 2.5.8
      expect(heights.chip!).toBeLessThanOrEqual(30);      // and not a button
    }
  });

  test('no ad-hoc pill radii survive in App.css', () => {
    const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8');
    expect(css).not.toContain('999px');
  });
});

test('sort is one switch defaulting to date', async ({ page }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');

  // It lives in the drawer's Settings section now, not the top bar.
  await openDrawer(page);
  // One control with two states, not two buttons that happen to be adjacent.
  const sw = page.getByRole('switch', { name: /sort by score/i });
  await expect(sw).toBeVisible();
  await expect(sw).toHaveAttribute('aria-checked', 'false');

  const sorted = page.waitForRequest((r) => r.url().includes('sort=score'));
  await sw.click();
  await sorted;
  await expect(sw).toHaveAttribute('aria-checked', 'true');
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

test('on a desktop the card metadata is a line, not a column', async ({ page, isMobile }) => {
  test.skip(isMobile, 'desktop only');
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');

  // The reading time, the source, the age and the Open link used to share a
  // 72px-wide column with the thumbnail, which stacked them into a 96px tower
  // that set the card's height while the reading column beside it ran short.
  // They belong on one line under the summary. Measured by height rather than
  // by rule, because the stacking came from the column's width, not from a
  // property any assertion could name.
  const meta = await page.locator('.article-row .article-left').first().boundingBox();
  expect(meta!.height).toBeLessThan(32);
  expect(meta!.width).toBeGreaterThan(100);
});

test('compact keeps the tags on a desktop, where they fit whole', async ({ page, isMobile }) => {
  test.skip(isMobile, 'desktop only');
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
  await page.evaluate(() => document.documentElement.setAttribute('data-density', 'compact'));

  // Compact means "drop the summary". Hiding the tags too was a phone-sized
  // judgement -- there they truncate to `copa-libert…` and read as clutter --
  // and the rule was written unscoped, so it also stripped them from a desktop
  // with 900px of room. The tag is what explains the score.
  await expect(page.locator('.article-row .article-summary').first()).toBeHidden();
  await expect(page.locator('.article-row .topic-chip').first()).toBeVisible();
});

test.describe('the drawer is five labelled sections', () => {
  test.beforeEach(async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await mockAdmin(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');
    await openDrawer(page);
  });

  test('in the order a reader reaches for them', async ({ page }) => {
    // It used to be one undivided list of feeds with an unlabelled tray of
    // icons underneath, so "where do I change the theme" had no answer you
    // could arrive at by looking.
    await expect(page.locator('.sidebar-section-title'))
      .toHaveText(['Feeds', 'Saved', 'Settings', 'You', 'Admin']);
  });

  test('the display preferences are all in Settings', async ({ page }) => {
    // Density and sort were in the top bar, where on a 390px screen they cost
    // a whole row of a header that was already a quarter of the viewport.
    const settings = page.locator('.sidebar-section').filter({ hasText: 'Settings' });
    await expect(settings.getByRole('switch', { name: 'Compact list' })).toBeVisible();
    await expect(settings.getByRole('switch', { name: /sort by score/i })).toBeVisible();
    await expect(settings.getByRole('radiogroup', { name: 'Theme' })).toBeVisible();

    // And gone from the top bar, or they would be in two places at once.
    await expect(page.locator('.site-header').getByRole('switch')).toHaveCount(0);
  });

  test('a plain reader gets four sections and no Admin', async ({ page }) => {
    await page.route('**/api/v1/me', (r) => r.fulfill({
      json: { id: 2, username: 'plain', role: 'user', must_change_password: false,
              declickbait: false, content_filter_mode: 'off' },
    }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await openDrawer(page);

    await expect(page.locator('.sidebar-section-title'))
      .toHaveText(['Feeds', 'Saved', 'Settings', 'You']);
    // Their own account and the way out stay theirs.
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
    await expect(page.getByRole('switch', { name: 'Compact list' })).toBeVisible();
  });
});

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

  test('every pill is the same height, on touch too', async ({ page, isMobile }) => {
    // The card's two pills -- the topic chip and the score badge -- were removed
    // by the whitespace redesign, so the sidebar's unread count is the only pill
    // left in the app. The rule it was protecting still holds for the survivor:
    // one pill shape, and on a coarse pointer a touch-safe one.
    const count = await page.evaluate(
      () => document.querySelector('.sidebar-feed-count')?.getBoundingClientRect().height ?? null,
    );
    expect(count, 'the sidebar count is the last pill; if it goes, delete this test')
      .not.toBeNull();
    if (isMobile) {
      expect(count!).toBeGreaterThanOrEqual(24);   // WCAG 2.5.8
      expect(count!).toBeLessThanOrEqual(30);      // and not a button
    }
  });

  test('no ad-hoc pill radii survive in App.css', () => {
    const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8');
    expect(css).not.toContain('999px');
  });
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
    await expect(page.locator('.site-header').getByRole('switch')).toHaveCount(0);
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

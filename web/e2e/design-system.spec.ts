import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { mockApi, signedIn } from './fixtures';

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
  { command: 'open settings', selector: '.settings-screen', label: 'Settings' },
  { command: 'manage feeds', selector: '.manage-feeds', label: 'Feeds' },
  { command: 'manage users', selector: '.admin-users', label: 'Users' },
  { command: 'open insights', selector: '.insights-screen', label: 'Insights' },
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
  const opener = page.locator('.sidebar-footer button').first();
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
  const CONTROLS = ['Settings', 'Users', 'Insights', 'Ollama log',
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
    const nameless = await page.locator('.sidebar-footer button, .sidebar-manage')
      .evaluateAll((els) => els
        .filter((el) => !el.textContent?.trim() && !el.getAttribute('aria-label'))
        .length);
    expect(nameless).toBe(0);
  });
});

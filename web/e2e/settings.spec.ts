import { expect, test } from '@playwright/test';
import { mockApi, signedIn } from './fixtures';

async function openSettings(page: import('@playwright/test').Page) {
  await page.keyboard.press('Control+k');
  await page.locator('.command-palette input').fill('open settings');
  await page.locator('.command-item').first().click();
  await page.waitForSelector('.settings-screen');
}

test.beforeEach(async ({ page }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
});

test('a plain reader is not offered settings at all', async ({ page }) => {
  // Every endpoint checks again; this is about not showing a door that 403s.
  await page.route('**/api/v1/me', (r) => r.fulfill({
    json: { id: 2, username: 'plain', role: 'user', declickbait: false, content_filter_mode: 'off' },
  }));
  await page.reload();
  await page.waitForSelector('.article-row');
  await page.keyboard.press('Control+k');
  await page.locator('.command-palette input').fill('open settings');
  await expect(page.locator('.command-item')).toHaveCount(0);
});

test('the Ollama panel says which endpoint is actually in force', async ({ page }) => {
  await openSettings(page);
  await expect(page.locator('.settings-panel').first())
    .toContainText('http://host.docker.internal:11434');
});

test('testing the connection reports the failure and saves nothing', async ({ page }) => {
  await openSettings(page);
  const panel = page.locator('.settings-panel').first();
  await panel.locator('input').first().fill('nowhere.invalid');
  await panel.locator('input').nth(1).fill('9999');

  let saved = false;
  await page.route('**/api/v1/settings/ollama', (r) => {
    if (r.request().method() === 'POST') saved = true;
    return r.fallback();
  });

  await panel.getByRole('button', { name: 'Test connection' }).click();
  await expect(panel.locator('.prefs-saved')).toContainText('Could not reach nowhere.invalid:9999');
  // Saving first and testing after is how a working setup gets replaced by a
  // broken one, so the probe must not write.
  expect(saved).toBe(false);
});

test('a model that is configured but not installed is called out', async ({ page }) => {
  await openSettings(page);
  const row = page.locator('.settings-table tr').filter({ hasText: 'Relevance scoring' });
  // This exact mismatch made every scoring call fail silently for six weeks.
  await expect(row.locator('.feed-error')).toContainText('ministral-3:14b is not installed');
  await expect(row).toContainText('Suggested: llama3.2:3b');
});

test('applying every recommendation clears the mismatch', async ({ page }) => {
  await openSettings(page);
  await page.getByRole('button', { name: 'Apply every recommendation' }).click();
  const row = page.locator('.settings-table tr').filter({ hasText: 'Relevance scoring' });
  await expect(row.locator('.feed-error')).toHaveCount(0);
});

test('a reader toggle round-trips rather than only flipping locally', async ({ page }) => {
  await openSettings(page);
  const toggle = page.locator('.settings-toggle').filter({ hasText: 'Rewrite clickbait' });
  const sent = page.waitForRequest((r) =>
    r.url().includes('/settings/reader') && r.method() === 'POST');
  // click(), not check(): check() asserts the new state the moment it clicks,
  // and these toggles only flip once the server has echoed the change back.
  await toggle.locator('input').click();
  const body = (await sent).postDataJSON() as { declickbait: boolean };
  expect(body.declickbait).toBe(true);
  await expect(toggle.locator('input')).toBeChecked();
});

test('retention ships inert: prune is unavailable until it is confirmed', async ({ page }) => {
  await openSettings(page);
  const prune = page.getByRole('button', { name: 'Prune now' });
  await expect(prune).toBeDisabled();

  await page.locator('.settings-toggle').filter({ hasText: 'deletes articles permanently' })
    .locator('input').click();
  await expect(prune).toBeEnabled();

  page.once('dialog', (d) => d.accept());
  await prune.click();
  await expect(page.locator('.settings-panel').filter({ hasText: 'never pruned' })
    .locator('.prefs-saved')).toContainText('412 articles deleted');
});

test('the retention window round-trips', async ({ page }) => {
  await openSettings(page);
  const panel = page.locator('.settings-panel').filter({ hasText: 'never pruned' });
  await panel.locator('input[type="number"]').fill('30');
  await panel.getByRole('button', { name: 'Save' }).click();
  await expect(panel).toContainText('older than 30 days');
});

test('muting a topic is an admin rule, and says so', async ({ page }) => {
  await openSettings(page);
  const panel = page.locator('.settings-panel').last();
  await expect(panel).toContainText('These apply to everyone');
  const row = panel.locator('tr').filter({ hasText: 'crypto' });
  await row.getByRole('button', { name: 'Mute' }).click();
  await expect(row.getByRole('button', { name: 'Mute' })).toHaveClass(/stance-on/);
});

test('tidying topics reports how many were re-tagged', async ({ page }) => {
  await openSettings(page);
  await page.getByRole('button', { name: 'Tidy existing topics' }).click();
  await expect(page.locator('.settings-panel').last().locator('.prefs-saved'))
    .toContainText('8 articles re-tagged');
});

import { expect, test } from '@playwright/test';
import { mockApi, signedIn } from './fixtures';

async function openSettings(page: import('@playwright/test').Page) {
  await page.keyboard.press('Control+k');
  await page.locator('.command-palette input').fill('server settings');
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
  await page.locator('.command-palette input').fill('server settings');
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
  const row = page.locator('.action-model').filter({ hasText: 'Relevance scoring' });
  // This exact mismatch made every scoring call fail silently for six weeks.
  await expect(row.locator('.ollama-result-bad'))
    .toContainText('ministral-3:14b is not installed');
  await expect(row).toContainText('Suggested: llama3.2:3b');
});

test('the panel explains why a job wants what it wants', async ({ page }) => {
  await openSettings(page);
  // The single most load-bearing text in Settings, and it was dropped entirely
  // when the panel was ported: it is what stops someone choosing a model that
  // fails silently on every call. The API was not even sending it.
  await expect(page.locator('.settings-panel').nth(1))
    .toContainText('spend their output budget thinking');
  const scoring = page.locator('.action-model').filter({ hasText: 'Relevance scoring' });
  await expect(scoring.locator('.action-guidance')).toContainText('dependable JSON');
  await expect(scoring.locator('.action-tag')).toHaveText(['JSON', 'every article']);
});

test('a defaulting job is distinguishable from a configured one', async ({ page }) => {
  await openSettings(page);
  // The resolved name alone cannot tell "set to llama3.2:3b" from "falling
  // back to it", which is the question this panel exists to answer.
  const summary = page.locator('.action-model').filter({ hasText: 'Article summaries' });
  await expect(summary.locator('select')).toHaveValue('');
  await expect(summary.locator('option').first()).toHaveText('Default (llama3.2:3b)');

  const scoring = page.locator('.action-model').filter({ hasText: 'Relevance scoring' });
  await expect(scoring.locator('select')).toHaveValue('ministral-3:14b');
  // Kept in the list rather than silently swapped out, or the panel would show
  // a model the server is not using.
  await expect(scoring.locator('option', { hasText: 'not installed' })).toHaveCount(1);
});

test('applying every recommendation clears the mismatch', async ({ page }) => {
  await openSettings(page);
  await page.getByRole('button', { name: 'Apply every recommendation' }).click();
  const row = page.locator('.action-model').filter({ hasText: 'Relevance scoring' });
  await expect(row.locator('.ollama-result-bad')).toHaveCount(0);
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
  const panel = page.locator('.settings-panel').filter({ hasText: 'These apply to everyone' });
  await expect(panel).toContainText('These apply to everyone');
  const row = panel.locator('tr').filter({ hasText: 'crypto' });
  await row.getByRole('button', { name: 'Mute' }).click();
  await expect(row.getByRole('button', { name: 'Mute' })).toHaveClass(/stance-on/);
});

test('tidying topics reports how many were re-tagged', async ({ page }) => {
  await openSettings(page);
  await page.getByRole('button', { name: 'Tidy existing topics' }).click();
  await expect(page.locator('.settings-panel').filter({ hasText: 'These apply to everyone' })
    .locator('.prefs-saved')).toContainText('8 articles re-tagged');
});

test.describe('prompts', () => {
  test('the whole prompt is visible, not the log’s truncation', async ({ page }) => {
    await openSettings(page);
    // The Ollama log stores 1,500 characters and the scoring prompt is about
    // twice that, so this was the only half you could not read.
    const row = page.locator('.prompt-rendered').filter({ hasText: 'Relevance scoring' });
    await row.locator('button').click();
    const text = await row.locator('pre').innerText();
    expect(text.length).toBeGreaterThan(1500);
    expect(text).toContain('<article_snippet>');
  });

  test('the locked parts are named on screen', async ({ page }) => {
    await openSettings(page);
    // A reader should be able to see what they cannot break, and why.
    await expect(page.locator('.prompt-locked li')).toHaveCount(3);
    await expect(page.locator('.prompt-locked')).toContainText('data, not instructions');
  });

  test('editing a slot changes what is sent', async ({ page }) => {
    await openSettings(page);
    const slot = page.locator('.prompt-slot').filter({ hasText: 'How many topics' });
    await slot.locator('textarea').fill('2-3');
    await slot.getByRole('button', { name: 'Save' }).click();
    await expect(slot.locator('.prefs-saved')).toBeVisible();

    const row = page.locator('.prompt-rendered').filter({ hasText: 'Relevance scoring' });
    await row.locator('button').click();
    await expect(row.locator('pre')).toContainText('2-3 lowercase slugs');
  });

  test('a bad edit is refused with the server’s reason', async ({ page }) => {
    await openSettings(page);
    const slot = page.locator('.prompt-slot').filter({ hasText: 'How many topics' });
    await slot.locator('textarea').fill('lots');
    await slot.getByRole('button', { name: 'Save' }).click();
    await expect(page.locator('.settings-panel').last().locator('.error'))
      .toContainText('range like 4-8');
  });

  test('an edited slot is marked, and resets', async ({ page }) => {
    await openSettings(page);
    const slot = page.locator('.prompt-slot').filter({ hasText: 'How many topics' });
    const reset = slot.getByRole('button', { name: 'Reset to default' });
    await expect(reset).toBeDisabled();

    await slot.locator('textarea').fill('2-3');
    await slot.getByRole('button', { name: 'Save' }).click();
    await expect(slot.locator('.kind-chip')).toHaveText('edited');

    await reset.click();
    await expect(slot.locator('textarea')).toHaveValue('4-8');
    await expect(slot.locator('.kind-chip')).toHaveCount(0);
  });
});

import { expect, test } from '@playwright/test';
import { mockAdmin, mockApi, signedIn } from './fixtures';

async function open(page: import('@playwright/test').Page, command: string, selector: string) {
  await page.keyboard.press('Control+k');
  await page.locator('.command-palette input').fill(command);
  await page.locator('.command-item').first().click();
  await page.waitForSelector(selector);
}

test.beforeEach(async ({ page }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
});

test('none of the admin screens are offered to a plain reader', async ({ page }) => {
  await page.route('**/api/v1/me', (r) => r.fulfill({
    json: { id: 2, username: 'plain', role: 'user', declickbait: false, content_filter_mode: 'off' },
  }));
  await page.reload();
  await page.waitForSelector('.article-row');
  for (const command of ['manage users', 'your stats', 'ollama log']) {
    await page.keyboard.press('Control+k');
    await page.locator('.command-palette input').fill(command);
    await expect(page.locator('.command-item')).toHaveCount(0);
    await page.keyboard.press('Escape');
  }
});

// ── users ─────────────────────────────────────────────────────────────────────

test('the user table shows activity and marks which row is you', async ({ page }) => {
  await open(page, 'manage users', '.admin-users');
  const mine = page.locator('.settings-table tr').filter({ hasText: 'reader' });
  await expect(mine).toContainText('you');
  await expect(mine).toContainText('34 votes');
});

test('delete is not offered on your own row', async ({ page }) => {
  await open(page, 'manage users', '.admin-users');
  const mine = page.locator('.settings-table tr').filter({ hasText: 'reader' });
  const theirs = page.locator('.settings-table tr').filter({ hasText: 'guest' });
  await expect(mine.getByRole('button', { name: 'Delete' })).toHaveCount(0);
  await expect(theirs.getByRole('button', { name: 'Delete' })).toHaveCount(1);
});

test('demoting the last admin is refused, in the server’s words', async ({ page }) => {
  // An instance with no admin cannot be repaired from inside the app.
  await open(page, 'manage users', '.admin-users');
  const mine = page.locator('.settings-table tr').filter({ hasText: 'reader' });
  await mine.locator('select').selectOption('user');
  await expect(page.locator('.error')).toContainText('last admin');
  // And the row did not change underneath the message.
  await expect(mine.locator('select')).toHaveValue('admin');
});

test('a reset password is shown once, with the consequence spelled out', async ({ page }) => {
  await open(page, 'manage users', '.admin-users');
  await page.locator('.settings-table tr').filter({ hasText: 'guest' })
    .getByRole('button', { name: 'Reset password' }).click();
  await expect(page.locator('.prefs-saved')).toContainText('temp-horse-battery');
  await expect(page.locator('.prefs-saved')).toContainText('not shown again');
  await expect(page.locator('.settings-table tr').filter({ hasText: 'guest' }))
    .toContainText('must change password');
});

test('deleting a user takes the row away', async ({ page }) => {
  await open(page, 'manage users', '.admin-users');
  page.once('dialog', (d) => d.accept());
  await page.locator('.settings-table tr').filter({ hasText: 'guest' })
    .getByRole('button', { name: 'Delete' }).click();
  await expect(page.locator('.settings-table tr').filter({ hasText: 'guest' })).toHaveCount(0);
});

// ── insights ──────────────────────────────────────────────────────────────────

test('insights draws the histogram without a charting library', async ({ page }) => {
  await open(page, 'your stats', '.insights-screen');
  const chart = page.locator('.bar-chart').first();
  await expect(chart.locator('.bar-primary')).toHaveCount(20);
  // The line marks the threshold: everything left of it is hidden.
  await expect(chart.locator('.bar-marker')).toHaveCount(1);
});

test('insights reports agreement and can adopt the suggested threshold', async ({ page }) => {
  await open(page, 'your stats', '.insights-screen');
  await expect(page.locator('.modal-body')).toContainText('76%');
  await expect(page.locator('.modal-body')).toContainText('0.45 would agree 84%');
  await page.getByRole('button', { name: 'Use it' }).click();
  await expect(page.locator('.prefs-saved')).toContainText('Threshold set to 0.45');
});

test('a run that took 90s shows its duration', async ({ page }) => {
  // A run reporting 0 scored in ~0s is a failing run, not an idle one.
  await open(page, 'your stats', '.insights-screen');
  const row = page.locator('.settings-table tr').filter({ hasText: '12 scored' });
  await expect(row).toContainText('90.0s');
  await expect(row).toContainText('1 errors');
});

// ── call log ──────────────────────────────────────────────────────────────────

test('the call log shows both sides of a call', async ({ page }) => {
  await open(page, 'ollama log', '.call-log');
  await page.locator('.call-summary').first().click();
  const detail = page.locator('.call-detail');
  await expect(detail).toContainText('Score these articles');
  await expect(detail).toContainText('{"scores": []}');
});

test('the log can be narrowed to failures, and says why they failed', async ({ page }) => {
  await open(page, 'ollama log', '.call-log');
  await expect(page.locator('.call-summary')).toHaveCount(2);
  await page.locator('.settings-toggle').filter({ hasText: 'Failures only' })
    .locator('input').check();
  await expect(page.locator('.call-summary')).toHaveCount(1);
  await expect(page.locator('.call-summary')).toContainText('connection refused');
});

test('an empty log still reports the queue', async ({ page }) => {
  // An empty log means either no calls are being made or none are needed.
  await open(page, 'ollama log', '.call-log');
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: 'Clear' }).click();
  await expect(page.locator('.call-summary')).toHaveCount(0);
  await expect(page.locator('.modal-body')).toContainText('Queue: 3 new');
});

test('recording is off until it is switched on', async ({ page }) => {
  await open(page, 'ollama log', '.call-log');
  const toggle = page.locator('.settings-toggle').filter({ hasText: 'Record calls' })
    .locator('input');
  await expect(toggle).not.toBeChecked();
  await toggle.click();
  await expect(toggle).toBeChecked();
});

test.describe('the threshold is reversible', () => {
  test.beforeEach(async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await mockAdmin(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');
    await open(page, 'your stats', '.insights-screen');
  });

  test('it can be set directly, not only adopted from a suggestion', async ({ page }) => {
    // "Use it" was the only control that moved this number. Adopting a
    // suggestion that hid every article was therefore a one-way door: the old
    // value is overwritten, and a reader staring at an empty list had nothing
    // left to fix it with.
    const sent: number[] = [];
    await page.route('**/api/v1/insights/threshold', async (r) => {
      sent.push((r.request().postDataJSON() as { threshold: number }).threshold);
      await r.fulfill({ json: { threshold: 0.2 } });
    });

    await page.locator('#threshold-input').fill('0.2');
    // `exact`: "Set" also substring-matches "Server settings" in the drawer
    // behind this dialog, and "Reset to default" beside it.
    await page.getByRole('button', { name: 'Set', exact: true }).click();
    await expect.poll(() => sent).toEqual([0.2]);
  });

  test('reset goes to the default, undo goes to the previous value', async ({ page }) => {
    const sent: number[] = [];
    await page.route('**/api/v1/insights/threshold', async (r) => {
      sent.push((r.request().postDataJSON() as { threshold: number }).threshold);
      await r.fulfill({ json: { threshold: 0.35 } });
    });

    await expect(page.getByRole('button', { name: /Undo — back to 0\.55/ })).toBeVisible();
    await page.getByRole('button', { name: /Undo — back to 0\.55/ }).click();
    await expect.poll(() => sent).toEqual([0.55]);

    // The fixture's current value *is* the default, so reset has nothing to do
    // and says so rather than sending a no-op request.
    await expect(page.getByRole('button', { name: /Reset to default/ })).toBeDisabled();
  });

  test('a threshold that hides everything says so', async ({ page }) => {
    // The number alone does not tell you the list is about to empty. This is
    // the state a reader actually got stuck in.
    await page.route('**/api/v1/insights', (r) => r.fulfill({ json: {
      threshold: 0.99, threshold_default: 0.35, threshold_previous: 0.35,
      histogram: [{ lo: 0.3, hi: 0.35, n: 120 }, { lo: 0.35, hi: 0.4, n: 80 }],
      agreement: { votes: 0, agreed: 0, rate: null, likes: 0, dislikes: 0,
                   likes_ok: 0, dislikes_ok: 0 },
      suggestion: null, per_feed: [], per_topic: [],
      pipeline: { unscored: 0, unsummarized: 0, hidden: 200, ready: 0, total: 200 },
      runs: [], llm_error: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await open(page, 'your stats', '.insights-screen');

    await expect(page.locator('.insights-screen')).toContainText('will be empty');
  });
});

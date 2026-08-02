import { expect, test } from '@playwright/test';
import { mockApi, signedIn } from './fixtures';

async function openFeeds(page: import('@playwright/test').Page) {
  await page.keyboard.press('Control+k');
  await page.locator('.command-palette input').fill('manage feeds');
  await page.locator('.command-item').first().click();
  await page.waitForSelector('.manage-feeds');
}

test.beforeEach(async ({ page }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
});

test('a failing feed shows why, and how often', async ({ page }) => {
  await openFeeds(page);
  // The 43-day silent outage is the reason this is on screen at all.
  const broken = page.locator('.feed-table tr').filter({ hasText: 'Broken' });
  await expect(broken.locator('.feed-error')).toContainText('Name or service not known');
  await expect(broken.locator('.feed-error')).toContainText('5×');
  await expect(broken).toHaveClass(/paused/);
});

test('an admin gets the controls', async ({ page }) => {
  await openFeeds(page);
  await expect(page.locator('.feed-add')).toBeVisible();
  await expect(page.locator('.feed-table tr').first().locator('.feed-actions button')).toHaveCount(2);
  await expect(page.locator('.opml-import')).toBeVisible();
});

test('a plain reader sees the feeds but not the controls', async ({ page }) => {
  // A button that 403s reads as breakage rather than as a permission.
  await page.route('**/api/v1/me', (r) => r.fulfill({
    json: { id: 2, username: 'plain', role: 'user', declickbait: false, content_filter_mode: 'off' },
  }));
  await page.reload();
  await page.waitForSelector('.article-row');
  await openFeeds(page);

  await expect(page.locator('.feed-table')).toContainText('The Verge');
  await expect(page.locator('.feed-add')).toHaveCount(0);
  await expect(page.locator('.opml-import')).toHaveCount(0);
});

test('exporting OPML downloads a file', async ({ page }) => {
  await page.route('**/api/v1/feeds/opml', (r) => r.fulfill({
    status: 200,
    headers: { 'content-disposition': 'attachment; filename="betternews-feeds-20260802.opml"' },
    body: '<?xml version="1.0"?><opml version="2.0"><body></body></opml>',
    contentType: 'text/x-opml',
  }));
  await openFeeds(page);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('.opml-actions button').first().click(),
  ]);
  // The filename has to come from the header: a bearer client cannot use
  // <a download>, so the URL never carries it.
  expect(download.suggestedFilename()).toBe('betternews-feeds-20260802.opml');
});

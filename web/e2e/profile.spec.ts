import { expect, test } from '@playwright/test';
import { mockApi, signedIn } from './fixtures';

test.beforeEach(async ({ page }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
  await page.keyboard.press('Control+k');
  await page.locator('.command-palette input').fill('profile');
  await page.locator('.command-item').first().click();
  await page.waitForSelector('.profile-screen');
});

test('the profile leads with the evidence, not the prose', async ({ page }) => {
  const evidence = page.locator('.prefs-evidence');
  await expect(evidence).toContainText('34');
  await expect(evidence).toContainText('4');
  // Stances are evidence too, and were ignored entirely before.
  await expect(page.locator('.prefs-stances')).toContainText('formula-1');
  await expect(page.locator('.prefs-textarea')).toHaveValue(/rockets/);
});

test('a new token is shown once and never in the list', async ({ page }) => {
  await expect(page.locator('.token-table')).toContainText('Old phone');
  // The list must never re-show a value.
  await expect(page.locator('.token-table')).not.toContainText('bn_');

  await page.locator('.token-form input').fill('iPhone');
  await page.locator('.token-form button').click();
  await expect(page.locator('.token-value')).toContainText('bn_brand-new-value');
});

test('changing a password reports success', async ({ page }) => {
  const form = page.locator('.password-form');
  await form.locator('input').nth(0).fill('current-pw');
  await form.locator('input').nth(1).fill('a-new-password');
  await form.locator('input').nth(2).fill('a-new-password');
  await form.locator('button').click();
  await expect(form.locator('.prefs-saved')).toContainText(/changed/i);
});

test('a rejected password change says why', async ({ page }) => {
  await page.route('**/api/v1/me/password', (r) =>
    r.fulfill({ status: 400, json: { error: 'Current password is wrong.', status: 400 } }));
  const form = page.locator('.password-form');
  await form.locator('input').nth(0).fill('nope');
  await form.locator('input').nth(1).fill('a-new-password');
  await form.locator('input').nth(2).fill('a-new-password');
  await form.locator('button').click();
  await expect(form.locator('.error')).toContainText(/current password is wrong/i);
});

test('topic stances can be set from the profile', async ({ page }) => {
  const row = page.locator('.topic-table tr').filter({ hasText: 'crypto' });
  await expect(row.locator('.stance-on')).toHaveCount(1);
  await row.locator('button').first().click();   // ▲ more
  await expect(row.locator('.btn-icon').first()).toHaveClass(/stance-on/);
});

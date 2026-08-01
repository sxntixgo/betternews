import { expect, test } from '@playwright/test';
import { mockApi, signedIn } from './fixtures';

/**
 * The first screen every reader meets, and the one they meet again when a token
 * is revoked. Neither was covered: the layout tests all start signed in.
 */
test.describe('signing in', () => {
  test('a bad token is refused at the form, not as an empty list', async ({ page }) => {
    await page.route('**/api/v1/me', (r) =>
      r.fulfill({ status: 401, json: { error: 'That token is not valid, or has been revoked.', status: 401 } }));
    await page.goto('/');

    await page.locator('.signin input').fill('bn_wrong');
    await page.locator('.signin button').click();

    // The message has to arrive here. Letting a bad token through and showing an
    // empty reading list is indistinguishable from having read everything.
    await expect(page.locator('.signin .error')).toContainText(/not valid|revoked/i);
    await expect(page.locator('.article-row')).toHaveCount(0);
  });

  test('a good token starts the app and survives a reload', async ({ page }) => {
    await mockApi(page);
    await page.goto('/');
    await page.locator('.signin input').fill('bn_good');
    await page.locator('.signin button').click();
    await expect(page.locator('.article-row').first()).toBeVisible();

    await page.reload();
    // Stored, so the reader is not asked again every time they open the app.
    await expect(page.locator('.article-row').first()).toBeVisible();
    await expect(page.locator('.signin')).toHaveCount(0);
  });

  test('the token is never shown once accepted', async ({ page }) => {
    await mockApi(page);
    await page.goto('/');
    await page.locator('.signin input').fill('bn_secret-value');
    await page.locator('.signin button').click();
    await expect(page.locator('.article-row').first()).toBeVisible();
    expect(await page.content()).not.toContain('bn_secret-value');
  });

  test('the field is a password field', async ({ page }) => {
    await page.goto('/');
    // Shoulder-surfing aside, this keeps it out of autofill and out of
    // screenshots taken while debugging.
    await expect(page.locator('.signin input')).toHaveAttribute('type', 'password');
  });
});

test.describe('losing the session', () => {
  test('a 401 mid-session returns to sign-in and forgets the token', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await expect(page.locator('.article-row').first()).toBeVisible();

    // The token is revoked on the server while the app is open.
    //
    // Only the vote endpoint. Intercepting **/api/v1/** also catches the
    // background feeds poll, and on a slower machine that 401s first, swaps in
    // the sign-in screen, and the button this test wants to click no longer
    // exists -- which is exactly how this passed locally and failed in CI.
    await page.route('**/api/v1/articles/*/vote', (r) =>
      r.fulfill({ status: 401, json: { error: 'revoked', status: 401 } }));
    await page.locator('.btn-like').first().click();

    await expect(page.locator('.signin')).toBeVisible();
    // Keeping a dead token means the next reload silently fails again.
    expect(await page.evaluate(() => localStorage.getItem('bn.token'))).toBeNull();
  });

  test('a server error is shown, and does not sign the reader out', async ({ page }) => {
    await signedIn(page);
    await page.route('**/api/v1/me', (r) => r.fulfill({ json: { id: 1, username: 'r', role: 'user', declickbait: false, content_filter_mode: 'off' } }));
    await page.route('**/api/v1/feeds', (r) => r.fulfill({ status: 500, json: { error: 'Internal error.', status: 500 } }));
    await page.route('**/api/v1/articles?*', (r) =>
      r.fulfill({ status: 500, json: { error: 'Internal error.', status: 500 } }));
    await page.goto('/');

    await expect(page.locator('.error')).toContainText(/internal error/i);
    // A 500 is the server's problem, not the credential's.
    await expect(page.locator('.signin')).toHaveCount(0);
  });
});

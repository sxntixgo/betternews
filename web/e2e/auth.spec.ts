import { expect, test } from '@playwright/test';
import { mockApi, mockEverything, signInFlow, signedIn } from './fixtures';

/**
 * The first screen every reader meets, and the one they meet again when a token
 * is revoked. Neither was covered: the layout tests all start signed in.
 */
test.describe('signing in', () => {
  test('a wrong password is refused at the form, not as an empty list', async ({ page }) => {
    await page.route('**/api/v1/me', (r) =>
      r.fulfill({ status: 401, json: { error: 'Not signed in.', status: 401 } }));
    await page.route('**/api/v1/auth/login', (r) =>
      r.fulfill({ status: 401, json: { error: 'Wrong username or password.', status: 401 } }));
    await page.goto('/');

    await page.locator('input[name=username]').fill('reader');
    await page.locator('input[name=password]').fill('wrong');
    await page.locator('.signin button').click();

    // The message has to arrive here. Letting a bad token through and showing an
    // empty reading list is indistinguishable from having read everything.
    await expect(page.locator('.signin .error')).toContainText(/wrong username or password/i);
    await expect(page.locator('.article-row')).toHaveCount(0);
  });

  test('correct credentials start the app and survive a reload', async ({ page }) => {
    await mockApi(page);
    await signInFlow(page);
    await page.goto('/');
    await page.locator('input[name=username]').fill('reader');
    await page.locator('input[name=password]').fill('right');
    await page.locator('.signin button').click();
    await expect(page.locator('.article-row').first()).toBeVisible();

    await page.reload();
    // Stored, so the reader is not asked again every time they open the app.
    await expect(page.locator('.article-row').first()).toBeVisible();
    await expect(page.locator('.signin')).toHaveCount(0);
  });

  test('no credential is left anywhere JavaScript can read', async ({ page }) => {
    // The whole point of the change: an HttpOnly cookie cannot be read by
    // injected script, and nothing else is stored. theme is the one sanctioned
    // localStorage key.
    await mockApi(page);
    await signInFlow(page);
    await page.goto('/');
    await page.locator('input[name=username]').fill('reader');
    await page.locator('input[name=password]').fill('hunter2');
    await page.locator('.signin button').click();
    await expect(page.locator('.article-row').first()).toBeVisible();

    const keys = await page.evaluate(() => Object.keys(localStorage));
    expect(keys.filter((k) => k !== 'theme')).toEqual([]);
    expect(await page.content()).not.toContain('hunter2');
  });

  test('the password field is a password field', async ({ page }) => {
    await page.route('**/api/v1/me', (r) => r.fulfill({ status: 401, json: { error: 'no', status: 401 } }));
    await page.goto('/');
    // Shoulder-surfing aside, this keeps it out of autofill and out of
    // screenshots taken while debugging.
    await expect(page.locator('input[name=password]')).toHaveAttribute('type', 'password');
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
    // Nothing to clear: the credential was never in the page's reach.
    const keys = await page.evaluate(() => Object.keys(localStorage));
    expect(keys.filter((k) => k !== 'theme')).toEqual([]);
  });

  test('a server error is shown, and does not sign the reader out', async ({ page }) => {
    await signedIn(page);
    // Everything except /me fails. A catch-all rather than a list, because the
    // list went stale twice as the shell grew new calls.
    await mockEverything(page, 500, { error: 'Internal error.', status: 500 });
    await page.goto('/');

    await expect(page.locator('.error')).toContainText(/internal error/i);
    // A 500 is the server's problem, not the credential's.
    await expect(page.locator('.signin')).toHaveCount(0);
  });
});

test('a reset password blocks the reading list until it is changed', async ({ page }) => {
  // The server used to enforce this with an app-wide redirect to the profile
  // page. That page is gone, so the SPA is the only thing left holding the gate.
  let changed = false;
  // mockApi registers its own /me, and Playwright tries the most recently
  // added route first -- so these have to come after it, not before.
  await mockApi(page);
  await page.route('**/api/v1/me', (r) => r.fulfill({
    json: { id: 1, username: 'reader', role: 'admin',
            must_change_password: !changed,
            declickbait: false, content_filter_mode: 'off' },
  }));
  await page.route('**/api/v1/me/password', (r) => {
    changed = true;
    return r.fulfill({ json: { ok: true } });
  });
  await page.goto('/');

  await expect(page.locator('.forced-password')).toBeVisible();
  await expect(page.locator('.article-row')).toHaveCount(0);

  await page.locator('input[autocomplete="current-password"]').fill('the-temp-one');
  const next = page.locator('input[autocomplete="new-password"]');
  await next.first().fill('a-much-better-one');
  await next.nth(1).fill('a-much-better-one');
  await page.getByRole('button', { name: 'Change password' }).click();

  await expect(page.locator('.forced-password')).toHaveCount(0);
  await expect(page.locator('.article-row').first()).toBeVisible();
});

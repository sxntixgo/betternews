import { expect, test } from '@playwright/test';

/**
 * End to end, against the running stack.
 *
 * Every other spec mocks the API, so none of them crosses the boundary where
 * this application has actually broken: the dev-server proxy, bearer auth
 * against real Flask, real serialization, and the real collapse-and-paginate
 * query over a real corpus.
 *
 *   export BN_E2E_TOKEN=$(../scripts/e2e-token.sh)
 *   npx playwright test --project=live
 *
 * Skips loudly rather than silently when the token is absent: a live suite that
 * quietly passes with nothing running is worse than no live suite.
 */
const TOKEN = process.env.BN_E2E_TOKEN;
const USER = process.env.BN_E2E_USER;
const PASS = process.env.BN_E2E_PASS;

test.describe('live stack', () => {
  test.skip(!TOKEN, 'set BN_E2E_TOKEN — see scripts/e2e-token.sh');

  test('an anonymous API call is refused with JSON, not a redirect', async ({ request }) => {
    // The bug this suite was written for. The session guard ran app-wide and
    // answered every /api/v1 call with a 302 to /login, including ones carrying
    // a valid token, and no mocked test could have seen it.
    const res = await request.get('/api/v1/me', { maxRedirects: 0 });
    expect(res.status(), 'a redirect here means the HTML guard is intercepting the API')
      .toBe(401);
    expect(res.headers()['content-type']).toContain('application/json');
  });

  test('a real token authenticates on its own', async ({ request }) => {
    const res = await request.get('/api/v1/me', {
      headers: { Authorization: `Bearer ${TOKEN}` },
      maxRedirects: 0,
    });
    expect(res.status()).toBe(200);
    expect((await res.json()).username).toBeTruthy();
  });

  test('signing in with a password reaches real articles', async ({ page }) => {
    test.skip(!USER || !PASS, 'set BN_E2E_USER and BN_E2E_PASS');
    await page.goto('/');
    await page.locator('input[name=username]').fill(USER!);
    await page.locator('input[name=password]').fill(PASS!);
    await page.locator('.signin button').click();
    await expect(page.locator('.article-row').first()).toBeVisible({ timeout: 30_000 });

    // Real data, real serialization: a title that came out of Postgres.
    const title = await page.locator('.article-title').first().innerText();
    expect(title.trim().length).toBeGreaterThan(3);
  });

  test('a vote survives a reload', async ({ page }) => {
    test.skip(!USER || !PASS, 'set BN_E2E_USER and BN_E2E_PASS');
    await signIn(page);

    // Pin the row by id before clicking. Filtering on
    // `.btn-like:not([disabled])` is fine for *finding* one, but voting
    // disables that button, so the same locator silently re-resolves to a
    // different row and the assertion checks the wrong article.
    const candidate = page.locator('.article-row')
      .filter({ has: page.locator('.btn-like:not([disabled])') }).first();
    const id = await candidate.getAttribute('id');
    const title = (await candidate.locator('.article-title').innerText()).trim();
    const row = page.locator(`#${id}`);

    await row.locator('.btn-like').click();
    await expect(row).toHaveClass(/liked/);

    // Persisted, not just optimistic: the whole point of the round trip.
    await page.reload();
    await page.waitForSelector('.article-row', { timeout: 30_000 });
    await expect(
      page.locator('.article-row').filter({ hasText: title }).first(),
    ).toHaveClass(/liked/);
  });

  test('paging the real corpus never repeats an article', async ({ request }) => {
    // The Phase A rewrite, exercised against real duplicate clusters rather
    // than fixtures. The old code repeated one article across 2,438.
    const seen: number[] = [];
    let offset: number | null = 0;
    let pages = 0;

    while (offset !== null && pages < 12) {
      const res = await request.get(`/api/v1/articles?limit=50&offset=${offset}`, {
        headers: { Authorization: `Bearer ${TOKEN}` },
      });
      expect(res.status()).toBe(200);
      const body = await res.json();
      seen.push(...body.articles.map((a: { id: number }) => a.id));
      offset = body.next_offset;
      pages += 1;
    }

    expect(seen.length, 'seed some articles first').toBeGreaterThan(0);
    expect(new Set(seen).size, 'an article appeared on two pages').toBe(seen.length);
  });

  test('the reader gets a real body, with padding folded not dropped', async ({ page }) => {
    test.skip(!USER || !PASS, 'set BN_E2E_USER and BN_E2E_PASS');
    await signIn(page);
    await page.locator('.article-title').first().click();

    const modal = page.locator('.modal-body');
    await expect(modal).toBeVisible();
    await expect(modal.locator('p').first()).not.toBeEmpty();
  });
});

/** Sign in for real, since there is no token to seed into the page any more. */
async function signIn(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.locator('input[name=username]').fill(USER!);
  await page.locator('input[name=password]').fill(PASS!);
  await page.locator('.signin button').click();
  await page.waitForSelector('.article-row', { timeout: 30_000 });
}

import { expect, test } from '@playwright/test';
import { mockApi, signedIn } from './fixtures';

/**
 * The SPA on a phone.
 *
 * The stylesheet was carried over from the server UI, which had months of
 * mobile fixes in it -- stacked action buttons, a sidebar that becomes a
 * drawer. Carrying CSS across does not carry the JavaScript those rules
 * expect, and that gap is invisible on a desktop viewport.
 */
test.describe('phone layout', () => {
  test.skip(({ isMobile }) => !isMobile, 'phone-only');

  test.beforeEach(async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');
  });

  test('the page never scrolls sideways', async ({ page }) => {
    // The single most common phone regression, and the one nobody notices on a
    // desktop: one over-wide element and the whole page rocks horizontally.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, 'horizontal overflow in px').toBeLessThanOrEqual(0);
  });

  test('the action buttons stack into a column', async ({ page }) => {
    const box = page.locator('.article-actions-inline').first();
    await expect(box).toHaveCSS('flex-direction', 'column');

    const buttons = await box.locator('.btn-icon').all();
    const tops = await Promise.all(buttons.map(async (b) => (await b.boundingBox())!.y));
    expect(new Set(tops).size, 'each button on its own row').toBe(buttons.length);
  });

  test('tap targets stay at least 40px', async ({ page }) => {
    for (const btn of await page.locator('.article-actions-inline .btn-icon').all()) {
      const box = (await btn.boundingBox())!;
      expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(40);
    }
  });

  test('the headline gets most of the width', async ({ page }) => {
    const title = (await page.locator('.article-title').first().boundingBox())!;
    const viewport = page.viewportSize()!.width;
    // Stacking the buttons exists to buy this; on a 390px screen the title was
    // 94px before that change and 182px after.
    expect(title.width / viewport).toBeGreaterThan(0.4);
  });

  test('the sidebar is reachable', async ({ page }) => {
    // At <=720px the stylesheet parks the sidebar off-screen and waits for a
    // toggle to add .open. Without one, a phone reader cannot switch feed or
    // reach Saved at all -- the sidebar is not hidden, it is unreachable.
    const sidebar = page.locator('.sidebar');
    const offscreen = (await sidebar.boundingBox())!.x + 260 <= 0;
    expect(offscreen, 'sidebar starts off-screen on a phone').toBe(true);

    await page.locator('.drawer-toggle').click();
    await expect(sidebar).toHaveClass(/open/);
    // The drawer slides in over 0.18s, so this has to retry rather than sample
    // once -- a single measurement lands mid-transition and reads negative.
    await expect
      .poll(async () => (await sidebar.boundingBox())!.x)
      .toBeGreaterThanOrEqual(0);

    await page.locator('.sidebar-feed').filter({ hasText: 'The Verge' }).click();
    await expect(sidebar).not.toHaveClass(/open/);
  });

  test('the reader goes full-bleed and folds padding', async ({ page }) => {
    await page.locator('.article-title').first().click();
    const modal = page.locator('.modal');
    await expect(modal).toBeVisible();
    const box = (await modal.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(page.viewportSize()!.width - 1);

    // Older-news rails fold, and are never dropped.
    const fold = page.locator('.aside-group');
    await expect(fold).toHaveCount(1);
    await expect(fold).not.toContainText('Older news rail', { useInnerText: true });
    await fold.locator('summary').click();
    await expect(fold).toContainText('Older news rail');
  });

  test('infinite scroll appends without repeating', async ({ page }) => {
    const before = await page.locator('.article-row').count();
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(page.locator('.article-row')).not.toHaveCount(before);

    const ids = await page.locator('.article-title').allInnerTexts();
    expect(new Set(ids).size, 'no article appears twice').toBe(ids.length);
  });
});

test.describe('desktop keeps its layout', () => {
  test.skip(({ isMobile }) => isMobile, 'desktop-only');

  test('actions stay in a row and the sidebar is always visible', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');

    await expect(page.locator('.article-actions-inline').first())
      .toHaveCSS('flex-direction', 'row');
    expect((await page.locator('.sidebar').boundingBox())!.x).toBeGreaterThanOrEqual(0);
    await expect(page.locator('.drawer-toggle')).toBeHidden();
  });
});

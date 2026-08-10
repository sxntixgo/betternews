import { test } from '@playwright/test';
import { mockAdmin, mockApi, openDrawer, signedIn } from './fixtures';
test('odd', async ({ page }) => {
  await signedIn(page); await mockApi(page); await mockAdmin(page);
  await page.goto('/'); await page.waitForSelector('.article-row');
  await page.screenshot({ path: 'e2e/tmp-bar.png', clip: { x: 0, y: 0, width: 390, height: 70 } });
  await openDrawer(page);
  const sort = page.getByRole('switch', { name: /sort by score/i });
  await sort.scrollIntoViewIfNeeded();
  const b = (await sort.boundingBox())!;
  await page.screenshot({ path: 'e2e/tmp-sort.png',
    clip: { x: 0, y: Math.max(0, b.y - 70), width: 280, height: 190 } });
});

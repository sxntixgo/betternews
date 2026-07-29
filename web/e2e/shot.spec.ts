import { test } from '@playwright/test';
import { mockApi, signedIn } from './fixtures';

/** Not an assertion — captures the phone layout for eyeballing. */
test('capture', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'phone-only');
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
  await page.screenshot({ path: 'e2e/phone-list.png' });
  await page.locator('.drawer-toggle').click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'e2e/phone-drawer.png' });
});

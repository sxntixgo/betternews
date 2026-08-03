import { expect, test } from '@playwright/test';
import { mockApi, signedIn } from './fixtures';

test.beforeEach(async ({ page }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
});

test.describe('keyboard', () => {
  test('j and k move the focus through the list', async ({ page }) => {
    await page.keyboard.press('j');
    await expect(page.locator('.article-row.focused')).toHaveCount(1);
    const first = await page.locator('.article-row.focused').getAttribute('id');
    await page.keyboard.press('j');
    expect(await page.locator('.article-row.focused').getAttribute('id')).not.toBe(first);
    await page.keyboard.press('k');
    expect(await page.locator('.article-row.focused').getAttribute('id')).toBe(first);
  });

  test('l likes the focused article', async ({ page }) => {
    await page.keyboard.press('j');
    await page.keyboard.press('l');
    await expect(page.locator('.article-row.focused')).toHaveClass(/liked/);
  });

  test('r opens the reader and Escape closes it', async ({ page }) => {
    await page.keyboard.press('j');
    await page.keyboard.press('r');
    await expect(page.locator('.modal')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('.modal')).toHaveCount(0);
  });

  test('typing in the search box does not fire shortcuts', async ({ page }) => {
    // The reason isEditableTarget exists: without it, searching for "jklo"
    // scrolls the list and likes things.
    await page.locator('#search').fill('jkr');
    await expect(page.locator('.article-row.focused')).toHaveCount(0);
    await expect(page.locator('.modal')).toHaveCount(0);
  });
});

test.describe('discoverability', () => {
  test('? lists the shortcuts', async ({ page }) => {
    await page.keyboard.press('?');
    const overlay = page.locator('.shortcuts-overlay');
    await expect(overlay).toBeVisible();
    // Five shortcuts existed and nothing announced them.
    for (const key of ['j', 'k', 'l', 'o', 'r']) {
      await expect(overlay).toContainText(key);
    }
    await page.keyboard.press('Escape');
    await expect(overlay).toHaveCount(0);
  });

  test('the command palette runs an action', async ({ page }) => {
    await page.keyboard.press('Control+k');
    const palette = page.locator('.command-palette');
    await expect(palette).toBeVisible();

    await palette.locator('input').fill('saved');
    await palette.locator('.command-item').first().click();
    await expect(palette).toHaveCount(0);
    await expect(page.locator('.sidebar-feed.active')).toContainText('Saved');
  });
});

test.describe('theme', () => {
  // Three icons now, not a dropdown: a three-state preference used this often
  // should not cost opening a menu to change.
  async function pick(page: import('@playwright/test').Page, name: string) {
    if (test.info().project.name === 'phone'
        && (await page.locator('.sidebar.open').count()) === 0) {
      await page.locator('.drawer-toggle').click();
    }
    await page.getByRole('radiogroup', { name: 'Theme' })
      .getByRole('radio', { name }).click();
  }

  test('offers system, light and dark', async ({ page }) => {
    await expect(page.getByRole('radiogroup', { name: 'Theme' })
      .getByRole('radio')).toHaveCount(3);
    await pick(page, 'Dark');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await pick(page, 'Light');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });

  test('the choice survives a reload', async ({ page }) => {
    await pick(page, 'Dark');
    await page.reload();
    await page.waitForSelector('.article-row');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    // Only UI preferences in localStorage, never a credential: the theme, and
    // the sidebar's collapsed groups, which are the same kind of thing.
    const keys = await page.evaluate(() => Object.keys(localStorage).sort());
    expect(keys).toContain('theme');
    expect(keys.every((k) => k === 'theme' || k === 'sidebar-collapsed')).toBe(true);
  });

  test('system follows the OS', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await pick(page, 'Follow the system');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });
});

test('the favicon carries the unread count', async ({ page }) => {
  // Drawn on a canvas, so the only observable is that the href became a data URL.
  await expect
    .poll(() => page.evaluate(() =>
      (document.getElementById('favicon') as HTMLLinkElement | null)?.href ?? ''))
    .toMatch(/^data:image\/png/);
});

test.describe('touch', () => {
  test.skip(({ isMobile }) => !isMobile, 'phone-only');

  /**
   * Drive a swipe with real Touch objects.
   *
   * TouchEvent will not accept plain objects for `touches` -- it needs actual
   * Touch instances, which is why the obvious version of this test throws
   * "Failed to convert value to 'Touch'".
   */
  async function swipe(page: import('@playwright/test').Page, path: [number, number][]) {
    await page.evaluate((pts) => {
      const [sx, sy] = pts[0];
      const el = document.elementFromPoint(sx, sy)!;
      const at = (x: number, y: number) =>
        [new Touch({ identifier: 0, target: el, clientX: x, clientY: y })];
      el.dispatchEvent(new TouchEvent('touchstart', { touches: at(sx, sy), bubbles: true }));
      for (const [x, y] of pts.slice(1)) {
        el.dispatchEvent(new TouchEvent('touchmove', { touches: at(x, y), bubbles: true }));
      }
      const [ex, ey] = pts[pts.length - 1];
      el.dispatchEvent(new TouchEvent('touchend', { changedTouches: at(ex, ey), bubbles: true }));
    }, path);
  }

  test('swiping right likes an article', async ({ page }) => {
    const box = (await page.locator('.article-row').first().boundingBox())!;
    const y = box.y + box.height / 2;
    await swipe(page, [[box.x + 30, y], [box.x + 60, y], [box.x + box.width * 0.7, y]]);
    await expect(page.locator('.article-row').first()).toHaveClass(/liked/);
  });

  test('a vertical drag scrolls instead of swiping', async ({ page }) => {
    // The decision is made once, on the first movement, and remembered --
    // deciding per event makes a diagonal scroll flicker between the two.
    const box = (await page.locator('.article-row').first().boundingBox())!;
    const y = box.y + box.height / 2;
    await swipe(page, [
      [box.x + 30, y], [box.x + 35, y - 60], [box.x + box.width * 0.7, y - 80],
    ]);
    await expect(page.locator('.article-row').first()).not.toHaveClass(/liked/);
  });
});

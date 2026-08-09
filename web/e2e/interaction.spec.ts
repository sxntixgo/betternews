import { expect, test } from '@playwright/test';
import { mockApi, openSearch, signedIn } from './fixtures';

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
    await openSearch(page);
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
  // `isMobile`, asked of the page, rather than the project name: a name check
  // meant adding a second phone-sized project silently skipped this, the drawer
  // stayed shut, and three tests failed on "the theme control does not exist" --
  // which reads exactly like the app being broken on that browser.
  async function pick(page: import('@playwright/test').Page, name: string) {
    if ((await page.locator('.drawer-toggle').isVisible())
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
    // Only UI preferences in localStorage, never a credential. This list is
    // the allowlist: anything new here should be a display choice with no auth
    // meaning, and adding to it should feel like a decision.
    const ALLOWED = ['theme', 'sidebar-collapsed', 'density'];
    const keys = await page.evaluate(() => Object.keys(localStorage).sort());
    expect(keys).toContain('theme');
    const unexpected = keys.filter((k) => !ALLOWED.includes(k));
    expect(unexpected, `unexpected localStorage keys: ${unexpected.join(', ')}`).toEqual([]);
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
   * Drive a swipe.
   *
   * Two ways to build the events, because the engines disagree. Chromium takes
   * real `Touch` instances and refuses plain objects for `touches` ("Failed to
   * convert value to 'Touch'"), which is why the obvious version fails there.
   * WebKit has no constructable `Touch` or `TouchEvent` at all -- both throw
   * "Illegal constructor" -- and WebKit is the engine these gestures actually
   * ship to.
   *
   * So: real objects where they exist, and a plain `Event` carrying the two
   * properties `useSwipe` reads where they do not. The fallback fakes the event
   * *shape*, but it drives the real listeners, the real 0.4 threshold and the
   * real scroll-versus-swipe decision. Skipping WebKit instead would leave the
   * gesture untested on the one browser a reader performs it in.
   */
  async function swipe(page: import('@playwright/test').Page, path: [number, number][]) {
    await page.evaluate((pts) => {
      const [sx, sy] = pts[0];
      const el = document.elementFromPoint(sx, sy)!;
      const native = (() => {
        try {
          new Touch({ identifier: 0, target: el, clientX: 0, clientY: 0 });
          return true;
        } catch {
          return false;
        }
      })();
      const at = (x: number, y: number) =>
        native
          ? [new Touch({ identifier: 0, target: el, clientX: x, clientY: y })]
          : ([{ identifier: 0, target: el, clientX: x, clientY: y }] as unknown as Touch[]);
      const fire = (type: string, list: Touch[]) => {
        if (native) {
          el.dispatchEvent(new TouchEvent(type, {
            touches: list, changedTouches: list, bubbles: true }));
          return;
        }
        const ev = new Event(type, { bubbles: true });
        Object.defineProperty(ev, 'touches', { value: list });
        Object.defineProperty(ev, 'changedTouches', { value: list });
        el.dispatchEvent(ev);
      };
      fire('touchstart', at(sx, sy));
      for (const [x, y] of pts.slice(1)) fire('touchmove', at(x, y));
      const [ex, ey] = pts[pts.length - 1];
      fire('touchend', at(ex, ey));
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

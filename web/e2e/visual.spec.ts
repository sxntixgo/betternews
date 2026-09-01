import { expect, test, type Page } from '@playwright/test';
import { article, mockApi, openDrawer, signedIn, signInFlow } from './fixtures';

/**
 * Visual regression coverage for task E.
 *
 * Every defect that reached the redesign's final review was invisible to the
 * rest of the suite -- the keyboard-focus row painted the same colour as its
 * background, `--font-ui` never applying because `App.css` restated a
 * different stack and won on source order, `ForcedPasswordChange` losing its
 * styling when sign-in was restyled (same root class, kept "working"), and a
 * single-story card stretching to 955px on desktop. Every one of those is a
 * pixel fact, not a DOM fact -- nothing here asserts a class name or a text
 * node, only what actually painted.
 *
 * Covers the four surfaces the redesign touched -- the reading list, the
 * drawer (open), sign-in, and single-story mode -- at phone and desktop
 * width, in light and dark. Deliberately not Settings, admin screens, modals
 * or Insights: they were not part of the redesign and their churn would cost
 * more than it catches (see the brief, `.superpowers/sdd/task-E-brief.md`).
 *
 * Runs on the `phone` and `desktop` projects only. `safari` carries the same
 * iPhone metrics as `phone` under a real WebKit engine rather than a third
 * viewport -- the pixel differences between Chromium's and WebKit's font
 * rasterizers are platform noise, not a regression this suite watches for,
 * and Playwright already keys a baseline to `{project}-{platform}` so
 * tripling it here would only be upkeep with nothing new to catch. Other
 * specs run WebKit for the *behavioural* coverage a real engine gives that a
 * DOM assertion can miss (see CLAUDE.md's note on the three-project split);
 * that reasoning does not carry over to a pixel diff.
 */
test.beforeEach(async ({}, testInfo) => {
  test.skip(testInfo.project.name === 'safari', 'covered by phone + desktop; see file header');
});

const THEMES = ['light', 'dark'] as const;

/**
 * Stamp the theme before the app's first paint, the way the brief asks:
 * `theme.ts` reads `localStorage.theme` on mount and stamps
 * `data-theme` on `<html>` from it, so setting the key via an init script
 * (which runs before any page script) means the app never has to be told
 * afterwards -- it boots straight into the theme under test rather than
 * flashing the default and then switching.
 */
async function forceTheme(page: Page, theme: 'light' | 'dark') {
  await page.addInitScript((t) => window.localStorage.setItem('theme', t), theme);
}

/**
 * Settle the two things that make a first screenshot lie about a second one:
 * the self-hosted fonts (`font-display: swap` means the fallback stack
 * paints first, and a screenshot mid-swap would be a timing artifact wearing
 * the shape of bug #2 above, not the bug itself) and any in-flight paint from
 * the transition just performed.
 */
async function settled(page: Page) {
  await page.evaluate(() => document.fonts.ready);
}

test.describe('reading list', () => {
  for (const theme of THEMES) {
    test(`${theme}`, async ({ page }) => {
      await forceTheme(page, theme);
      await signedIn(page);
      await mockApi(page);
      await page.goto('/');
      await page.waitForSelector('.article-row');
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await settled(page);
      // .meta-age is "6w", "2h", "now" -- relative to the moment the test
      // runs, not to the fixture's fixed published_at. Left unmasked it would
      // fail every snapshot within the hour, which is exactly the trap the
      // brief calls out by name.
      await expect(page).toHaveScreenshot(`list-${theme}.png`, {
        mask: [page.locator('.meta-age')],
      });
    });
  }
});

test.describe('drawer, open', () => {
  for (const theme of THEMES) {
    test(`${theme}`, async ({ page }) => {
      await forceTheme(page, theme);
      await signedIn(page);
      await mockApi(page);
      await page.goto('/');
      await page.waitForSelector('.article-row');
      // Waits for the shell before clicking and for the slide-in transition
      // to actually finish, not merely start -- see its own comment in
      // fixtures.ts for the flake this fixed. On desktop the drawer is
      // already a permanent column, so this is a no-op there.
      await openDrawer(page);
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await settled(page);
      await expect(page).toHaveScreenshot(`drawer-${theme}.png`, {
        mask: [page.locator('.meta-age')],
      });
    });
  }
});

test.describe('sign in', () => {
  for (const theme of THEMES) {
    test(`${theme}`, async ({ page }) => {
      await forceTheme(page, theme);
      await signInFlow(page);
      await page.goto('/');
      await page.waitForSelector('.signin');
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      // The username field is autofocused. `toHaveScreenshot` freezes CSS
      // animations, but a text caret's blink is native browser rendering, not
      // a CSS animation -- left alone it is a coin flip whether a given
      // screenshot catches the caret on or off, which is exactly the kind of
      // instability the brief says to find and mask rather than paper over
      // with a looser threshold. Blurring removes the caret from the frame
      // outright instead of trying to freeze it mid-blink.
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      await settled(page);
      await expect(page).toHaveScreenshot(`signin-${theme}.png`);
    });
  }
});

test.describe('single-story mode', () => {
  for (const theme of THEMES) {
    test(`${theme}`, async ({ page }) => {
      await forceTheme(page, theme);
      await signedIn(page);
      await mockApi(page, [article(1), article(2), article(3)]);
      await page.goto('/');
      await page.waitForSelector('.article-row');
      await openDrawer(page);
      await page.getByRole('button', { name: 'One at a time' }).click();
      await page.waitForSelector('.single-story');
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await settled(page);
      // .single-age is the same relative-time label as the list's .meta-age,
      // rendered by SingleStory instead of ArticleCard -- same clock, same
      // reason to mask it.
      await expect(page).toHaveScreenshot(`single-story-${theme}.png`, {
        mask: [page.locator('.single-age')],
      });
    });
  }
});

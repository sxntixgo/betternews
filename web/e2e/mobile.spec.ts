import { expect, test } from '@playwright/test';
import { article, mockApi, signedIn } from './fixtures';

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

  test('the buttons never sit beside the headline', async ({ page }) => {
    // This used to assert the buttons stacked into a column, which was the
    // mechanism rather than the goal: a column kept them out of the headline's
    // way, and cost 128px of height doing it -- the tallest thing on the card.
    // They are a row on the meta line now, below the text, which serves the
    // same goal better. The test asserts the goal.
    const title = (await page.locator('.article-title').first().boundingBox())!;
    const actions = (await page.locator('.article-actions-inline').first().boundingBox())!;
    expect(actions.y, 'actions belong below the headline, not beside it')
      .toBeGreaterThanOrEqual(title.y + title.height - 1);
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

    // The Verge is listed under its tag and again under Hidden, so this has to
    // say which. Picking a feed closes the drawer either way.
    await page.locator('.sidebar-group').filter({ hasText: 'tech' })
      .locator('.sidebar-feed').filter({ hasText: 'The Verge' }).first().click();
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
  test('the card is compact enough to see five at a time', async ({ page }) => {
    // Measured before this layout: 175px per card on a 664px viewport, so
    // fewer than four fitted and reading the list was mostly scrolling. The
    // height was not where it looked -- the three vote buttons stacked into a
    // 128px column and the tags took a row of their own.
    const m = await page.evaluate(() => {
      const row = document.querySelector('.article-row') as HTMLElement;
      const h = row.getBoundingClientRect().height;
      return { h, perScreen: window.innerHeight / h };
    });
    expect(m.h).toBeLessThan(145);
    expect(m.perScreen).toBeGreaterThan(4.5);
  });
  test('the meta line stays on one line', async ({ page }) => {
    // Everything small shares a row with the actions. If any of it wraps, the
    // card grows by a whole line and the layout has failed at its one job.
    const row = page.locator('.article-row').first();
    const heights = await row.evaluate((el) => {
      const g = (s: string) => {
        const n = el.querySelector(s) as HTMLElement | null;
        return n ? n.getBoundingClientRect().height : 0;
      };
      return { left: g('.article-left'), chips: g('.topic-chips'),
               actions: g('.article-actions-inline') };
    });
    // 41, not 40: the action buttons are deliberately 40px tap targets, so a
    // single row of them is exactly 40 and only a wrap exceeds it.
    for (const [name, h] of Object.entries(heights)) {
      expect(h, `${name} wrapped onto a second line`).toBeLessThan(41);
    }
  });
  test('long tags truncate, and a long list is capped', async ({ page }) => {
    // The fixtures use "economy" and "politics". Real topics here are
    // "copa-libertadores" and "buenos-aires", and six on one article is
    // ordinary -- at which point container-level clipping cut a tag mid-word
    // at whatever column the edge fell on.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [
        article(1, { kind: 'match-report',
                     topics: ['copa-libertadores', 'boca-juniors', 'argentina', 'football'] }),
        article(2, { kind: 'analysis',
                     topics: ['immigration', 'us', 'politics', 'democracy', 'conflict', 'economy'] }),
      ],
      next_offset: null, diagnosis: null } }));
    await page.reload();
    await page.waitForSelector('.article-row');

    const rows = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.article-row')).map((row) => {
        const chips = row.querySelector('.topic-chips') as HTMLElement;
        const shown = Array.from(chips.children)
          .filter((c) => getComputedStyle(c).display !== 'none') as HTMLElement[];
        return {
          height: Math.round(row.getBoundingClientRect().height),
          shown: shown.length,
          // Ellipsis rather than a slice: the box is narrower than the text.
          truncated: shown.some((c) => c.scrollWidth > c.clientWidth + 1),
          rowClipped: chips.scrollWidth > chips.clientWidth + 1,
        };
      }));

    for (const r of rows) {
      expect(r.shown, 'at most two tags share the meta line').toBeLessThanOrEqual(2);
      expect(r.rowClipped, 'the row must not clip a tag mid-word').toBe(false);
      expect(r.height, 'long tags must not grow the card').toBeLessThan(145);
    }
    // The four-topic article has a long kind and a long first topic, so at
    // least one of them has to be ellipsised rather than escaping its box.
    expect(rows[0].truncated).toBe(true);
  });

  test('compact mode trades summaries for stories on screen', async ({ page }) => {
    // Hiding tags alone saves nothing: they share the meta line with the
    // action buttons, whose 40px tap target sets that row's height either way.
    // The summary is the entire saving, which is why the toggle covers both.
    const height = () => page.evaluate(() =>
      (document.querySelector('.article-row') as HTMLElement).getBoundingClientRect().height);

    const comfortable = await height();
    await page.getByRole('switch', { name: 'Compact list' }).click();
    const compact = await height();

    expect(compact).toBeLessThan(comfortable - 30);
    const perScreen = await page.evaluate(() =>
      window.innerHeight /
      (document.querySelector('.article-row') as HTMLElement).getBoundingClientRect().height);
    expect(perScreen).toBeGreaterThan(6);

    await expect(page.locator('.article-summary').first()).toBeHidden();
    await expect(page.locator('.topic-chip').first()).toBeHidden();
  });

  test('the kind survives compact, because it explains the score', async ({ page }) => {
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [article(1, { kind: 'fixture', topics: ['boca-juniors'] })],
      next_offset: null, diagnosis: null } }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await page.getByRole('switch', { name: 'Compact list' }).click();
    // A fixture listing and a transfer story are the same subject and opposite
    // value; dropping that word would hide the reason for the score.
    await expect(page.locator('.kind-chip')).toHaveText('fixture');
    await expect(page.locator('.topic-chip')).toBeHidden();
  });

  test('the density choice survives a reload', async ({ page }) => {
    await page.getByRole('switch', { name: 'Compact list' }).click();
    await page.reload();
    await page.waitForSelector('.article-row');
    await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');
    await expect(page.getByRole('switch', { name: 'Compact list' }))
      .toHaveAttribute('aria-checked', 'true');
  });

  test('the meta line carries the source and the age', async ({ page }) => {
    // The row is held open by the 40px tap targets whatever else is on it, so
    // these cost no height -- and once the tags were hidden in compact mode it
    // was mostly empty. Which paper ran it and how old it is are what a reader
    // weighs before opening a headline.
    const now = Date.now();
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [
        article(1, { feed_id: 8, published_at: new Date(now - 2 * 3600e3).toISOString() }),
        article(2, { feed_id: 7, published_at: new Date(now - 30e3).toISOString() }),
        article(3, { feed_id: 7, published_at: null }),
      ],
      next_offset: null, diagnosis: null } }));
    await page.reload();
    await page.waitForSelector('.article-row');

    const rows = page.locator('.article-row');
    await expect(rows.nth(0).locator('.article-source')).toHaveText('LA NACION');
    await expect(rows.nth(0).locator('.article-age')).toHaveText('2h');
    await expect(rows.nth(1).locator('.article-age')).toHaveText('now');
    // No date is common in feeds; it renders as nothing rather than "NaN".
    await expect(rows.nth(2).locator('.article-age')).toHaveCount(0);

    // Still one line, and still short enough to fit beside everything else.
    for (const h of await rows.nth(0).evaluate((el) => [
      (el.querySelector('.article-left') as HTMLElement).getBoundingClientRect().height,
    ])) expect(h).toBeLessThan(41);
  });

  test('the source and age survive compact mode', async ({ page }) => {
    await page.getByRole('switch', { name: 'Compact list' }).click();
    await expect(page.locator('.article-source').first()).toBeVisible();
    await expect(page.locator('.article-age').first()).toBeVisible();
  });

  test('the meta row does not overlap itself', async ({ page }) => {
    // The left column keeps a fixed 72px width on desktop; as a row that made
    // the Open link overflow and sit on top of the tags.
    const boxes = await page.locator('.article-row').first().evaluate((el) => {
      const b = (s: string) => {
        const n = el.querySelector(s) as HTMLElement | null;
        return n ? n.getBoundingClientRect() : null;
      };
      const left = b('.article-left'); const chips = b('.topic-chips');
      return left && chips ? { leftRight: left.right, chipsLeft: chips.left } : null;
    });
    if (boxes) expect(boxes.leftRight).toBeLessThanOrEqual(boxes.chipsLeft + 1);
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

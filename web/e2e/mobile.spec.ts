import { expect, test } from '@playwright/test';
import { DETAIL, article, mockAdmin, mockApi, openDrawer, signedIn } from './fixtures';

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
  test('the card stays under four screens-worth of scrolling', async ({ page }) => {
    // A ratchet, not a target. The history is worth keeping: 175px per card
    // originally, 139px after the compaction work, and ~179px now that the card
    // carries a photo and shows every tag on a row of its own. That last move
    // cost roughly one card per screen and was asked for deliberately -- the
    // point of this test is that it does not quietly cost another.
    const m = await page.evaluate(() => {
      const row = document.querySelector('.article-row') as HTMLElement;
      const h = row.getBoundingClientRect().height;
      return { h, perScreen: window.innerHeight / h };
    });
    expect(m.h).toBeLessThan(195);
    expect(m.perScreen).toBeGreaterThan(3.4);
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
  test('a long tag is shown whole, and a long list wraps', async ({ page }) => {
    // The opposite of what this asserted before. The 13ch cap and the two-tag
    // limit were both bought by the old single-line layout, where the tags
    // competed with the vote buttons for the same 356px and "copa-libertadores"
    // rendered as "copa-libert…". They have a row to themselves now.
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
        const shown = Array.from(chips.querySelectorAll('.pill'))
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
      expect(r.rowClipped, 'the row must not clip a tag mid-word').toBe(false);
      // Nothing is ellipsised any more: the row wraps instead, which is what
      // having a row of its own buys.
      expect(r.truncated, 'a tag was truncated despite having room').toBe(false);
    }
    // Every tag, not a capped two. The five- and six-topic articles are the
    // ordinary case here, not the edge.
    expect(rows[0].shown).toBe(5);      // 4 topics + the kind
    expect(rows[1].shown).toBe(7);      // 6 topics + the kind
  });

  test('compact mode trades summaries for stories on screen', async ({ page }) => {
    // Hiding tags alone saves nothing: they share the meta line with the
    // action buttons, whose 40px tap target sets that row's height either way.
    // The summary is the entire saving, which is why the toggle covers both.
    const height = () => page.evaluate(() =>
      (document.querySelector('.article-row') as HTMLElement).getBoundingClientRect().height);

    const comfortable = await height();
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Compact list' }).click();
    const compact = await height();

    expect(compact).toBeLessThan(comfortable - 30);
    const perScreen = await page.evaluate(() =>
      window.innerHeight /
      (document.querySelector('.article-row') as HTMLElement).getBoundingClientRect().height);
    expect(perScreen).toBeGreaterThan(4.5);

    await expect(page.locator('.article-summary').first()).toBeHidden();
    await expect(page.locator('.topic-chip').first()).toBeHidden();
  });

  test('the kind survives compact, because it explains the score', async ({ page }) => {
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [article(1, { kind: 'fixture', topics: ['boca-juniors'] })],
      next_offset: null, diagnosis: null } }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Compact list' }).click();
    // A fixture listing and a transfer story are the same subject and opposite
    // value; dropping that word would hide the reason for the score.
    await expect(page.locator('.kind-chip')).toHaveText('fixture');
    await expect(page.locator('.topic-chip')).toBeHidden();
  });

  test('the density choice survives a reload', async ({ page }) => {
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Compact list' }).click();
    await page.reload();
    await page.waitForSelector('.article-row');
    await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');
    await openDrawer(page);
    await expect(page.getByRole('switch', { name: 'Compact list' }))
      .toHaveAttribute('aria-checked', 'true');
  });

  test('the last row leads with the source and the age', async ({ page }) => {
    // They led the *meta* row until the card became three rows. Six items would
    // not fit 356px -- that row wrapped to three lines -- and these two are the
    // ones a reader reads rather than presses, so they moved down to sit with
    // the tags.
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

    // They lead the tags row, ahead of the pills, and that row stays one line
    // for an article with few tags.
    const chips = rows.nth(0).locator('.topic-chips');
    await expect(chips.locator('.article-source')).toHaveCount(1);
    expect((await chips.boundingBox())!.height).toBeLessThan(30);
  });

  test('the source and age survive compact mode', async ({ page }) => {
    await openDrawer(page);
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

test.describe('the top bar and the drawer fit the screen', () => {
  test.beforeEach(async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await mockAdmin(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');
  });

  test('on a phone the actions are icons, and still have names', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // Measured before: Refresh, Dismiss all, What you missed and the field
    // wrapped onto three rows -- a 173px header on a 664px screen, a quarter of
    // the viewport spent before the first headline.
    const header = (await page.locator('.site-header').boundingBox())!;
    expect(header.height).toBeLessThan(130);

    for (const id of ['#poll-btn', '#dismiss-all-btn', '#digest-btn']) {
      await expect(page.locator(`${id} .btn-label`)).toBeHidden();
    }
    // Hiding the text must not leave a nameless button.
    for (const name of ['Refresh', 'Dismiss all', 'What you missed', 'Search articles']) {
      await expect(page.getByRole('button', { name })).toBeVisible();
    }
  });

  test('on a phone the search field is behind a button', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // It used to be squeezed into whatever width was left, which was 53px --
    // a field showing "Fi".
    await expect(page.locator('#search')).toBeHidden();
    await page.getByRole('button', { name: 'Search articles' }).click();

    const field = page.locator('#search');
    await expect(field).toBeVisible();
    await expect(field).toBeFocused();      // opening it must not cost a second tap
    expect((await field.boundingBox())!.width).toBeGreaterThan(200);

    await field.fill('peso');
    await expect(page.locator('#search')).toHaveValue('peso');
  });

  test('/ opens the field wherever it is hiding', async ({ page }) => {
    // `/` focused the input directly. Focusing a hidden input silently does
    // nothing, so on a phone the shortcut did nothing at all -- and an external
    // keyboard on a tablet is exactly where someone would press it.
    await page.keyboard.press('/');
    await expect(page.locator('#search')).toBeFocused();
  });

  test('on a desktop the words are still there', async ({ page, isMobile }) => {
    test.skip(isMobile, 'desktop only');
    await expect(page.locator('#digest-btn')).toContainText('What you missed');
    await expect(page.locator('#search')).toBeVisible();
    // The toggle is a phone affordance; a desktop has room for the field.
    await expect(page.locator('.search-toggle')).toBeHidden();
  });

  test('a long feed list does not strand the lower sections', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The drawer is five stacked sections and the feed list is the first, so
    // with thirty feeds everything below it is off-screen until you scroll.
    // What matters is that scrolling reaches them: an earlier version made the
    // whole sidebar `overflow: hidden` to pin a footer that no longer exists,
    // which would leave Settings, You and Admin unreachable on a phone -- the
    // one place nothing else opens them.
    await page.route('**/api/v1/feeds', (r) => r.fulfill({ json: {
      feeds: Array.from({ length: 30 }, (_, i) => ({
        id: i + 1, title: `Feed number ${i + 1}`, unread: i, hidden: 0,
        saved: 0, paused: false, tags: [],
      })),
      unread: 400, saved: 0, hidden: 0,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await openDrawer(page);

    const admin = page.locator('.sidebar-section').filter({ hasText: 'Admin' });
    await admin.scrollIntoViewIfNeeded();

    const vp = page.viewportSize()!;
    for (const name of ['Sign out', 'Ollama log']) {
      const box = (await page.getByRole('button', { name }).boundingBox())!;
      expect(box.y + box.height, `${name} was not reachable`).toBeLessThanOrEqual(vp.height);
      expect(box.y, `${name} was above the viewport`).toBeGreaterThanOrEqual(0);
    }
    await expect(page.getByRole('radiogroup', { name: 'Theme' })).toBeAttached();
  });
});

test.describe('photos', () => {
  const PIXEL = 'data:image/gif;base64,R0lGODlhAQABAIABAP8AAP///yH5BAEAAAEALAAAAAABAAEAAAICTAEAOw==';

  test.beforeEach(async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [1, 2, 3].map((i) => article(i, {
        thumbnail_url: PIXEL,
        kind: 'fixture',
        topics: ['boca-juniors', 'copa-libertadores', 'football'],
      })),
      next_offset: null, diagnosis: null,
    } }));
    await page.goto('/');
    await page.waitForSelector('.article-row');
  });

  test('the headline sits beside the photo, not under it', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // "Costs no height" is not the claim any more and would be false: the photo
    // floats, so on a short headline it is the tallest thing on the card and it
    // does set the height. What it must not do is take a row of its own, which
    // is what the old grid column did -- reserving width down the whole card
    // whether or not a photo was in it.
    const thumb = (await page.locator('.article-row .article-thumb').first().boundingBox())!;
    expect(thumb.width).toBe(72);

    const title = (await page.locator('.article-row .article-title').first().boundingBox())!;
    expect(title.x, 'the headline was pushed below the photo')
      .toBeGreaterThanOrEqual(thumb.x + thumb.width);
    expect(title.y, 'the headline starts level with the photo, not after it')
      .toBeLessThan(thumb.y + thumb.height);
  });

  test('compact drops the tags but keeps the kind', async ({ page }) => {
    // The photo used to displace the tags, because both wanted the same 356px
    // line. They have a row of their own now, so nothing displaces them -- but
    // compact still drops them, which on a six-topic article is two lines back.
    // The kind stays: one short word, and the one that explains the score.
    const row = page.locator('.article-row').first();
    await expect(row.locator('.topic-chip').first()).toBeVisible();

    await openDrawer(page);
    await page.getByRole('switch', { name: 'Compact list' }).click();

    await expect(row.locator('.topic-chip').first()).toBeHidden();
    await expect(row.locator('.kind-chip')).toBeVisible();
    await expect(row.locator('.article-summary')).toBeHidden();
  });

  test('a card with no photo keeps its tags', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The trade above is bought by `:has()`, so it applies only where a photo
    // actually takes the width.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [article(1, { thumbnail_url: null, topics: ['economy'] })],
      next_offset: null, diagnosis: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await expect(page.locator('.article-row .topic-chip').first()).toBeVisible();
  });

  test('the reader leads with the photo', async ({ page }) => {
    // The detail endpoint is its own fixture; the list mock above does not
    // reach it.
    await page.route('**/api/v1/articles/*', (r) => {
      if (r.request().method() !== 'GET') return r.fallback();
      return r.fulfill({ json: { ...DETAIL, thumbnail_url: PIXEL } });
    });
    await page.locator('.article-title').first().click();
    const lead = page.getByRole('dialog').locator('.modal-lead');
    await expect(lead).toBeVisible();
    // Its own image, not a body image: extraction is text-only, and the embed
    // cards deliberately load nothing from a third party.
    await expect(lead).toHaveAttribute('src', PIXEL);
  });
});

test.describe('the photos toggle', () => {
  const PIXEL = 'data:image/gif;base64,R0lGODlhAQABAIABAP8AAP///yH5BAEAAAEALAAAAAABAAEAAAICTAEAOw==';

  test.beforeEach(async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [1, 2, 3].map((i) => article(i, { thumbnail_url: PIXEL })),
      next_offset: null, diagnosis: null,
    } }));
    await page.goto('/');
    await page.waitForSelector('.article-row');
  });

  test('turns the photos off and gives the width back', async ({ page }) => {
    // Not the same lever as compact. That drops text the model produced; this
    // drops the only thing on a card fetched from a third party.
    const thumb = page.locator('.article-row .article-thumb').first();
    await expect(thumb).toBeVisible();
    const indented = (await page.locator('.article-row .article-title').first().boundingBox())!.x;

    await openDrawer(page);
    await page.getByRole('switch', { name: 'Show photos' }).click();

    await expect(thumb).toBeHidden();
    // The headline reclaims the space rather than leaving a hole where the
    // photo was -- the point of a float over a reserved column.
    const flush = (await page.locator('.article-row .article-title').first().boundingBox())!.x;
    expect(flush).toBeLessThan(indented);
  });

  test('the choice survives a reload', async ({ page }) => {
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Show photos' }).click();
    await page.reload();
    await page.waitForSelector('.article-row');
    await expect(page.locator('html')).toHaveAttribute('data-photos', 'off');
    await expect(page.locator('.article-row .article-thumb').first()).toBeHidden();
  });

  test('it takes the reader lead image with it', async ({ page }) => {
    // Turning photos off did not mean "except the big one".
    await page.route('**/api/v1/articles/*', (r) => {
      if (r.request().method() !== 'GET') return r.fallback();
      return r.fulfill({ json: { ...DETAIL, thumbnail_url: PIXEL } });
    });
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Show photos' }).click();
    // Shut the drawer: on a phone it covers the list, and Escape does not close
    // it -- it is not a dialog.
    const toggle = page.locator('.drawer-toggle');
    if (await toggle.isVisible()) await toggle.click();
    await expect(page.locator('.sidebar.open')).toHaveCount(0);

    await page.locator('.article-title').first().click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByRole('dialog').locator('.modal-lead')).toBeHidden();
  });
});

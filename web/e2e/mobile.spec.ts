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
    const actions = (await page.locator('.article-actions').first().boundingBox())!;
    expect(actions.y, 'actions belong below the headline, not beside it')
      .toBeGreaterThanOrEqual(title.y + title.height - 1);
  });

  test('tap targets clear the WCAG floor', async ({ page }) => {
    // 24, not the old 40. That 40 was the icon buttons' own spec; the redesign
    // replaced them with text labels, and "Up" is 15px of glyphs. 24x24 is
    // WCAG 2.5.8, and `.action` earns it with padding plus a negative margin
    // rather than by growing.
    //
    // This asserted `.btn-icon` for one commit after the card was rewritten.
    // That class had stopped existing, so `.all()` returned nothing, the loop
    // never ran, and the test passed while checking nothing at all.
    const boxes = await page.locator('.article-actions .action').all();
    expect(boxes.length, 'no actions found -- this test is asserting nothing')
      .toBeGreaterThan(0);
    for (const btn of boxes) {
      const box = (await btn.boundingBox())!;
      expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(24);
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
      return { meta: g('.article-meta'), actions: g('.article-actions') };
    });
    // 41, not 40: the actions set the line's height at exactly 40, so only a
    // genuine wrap exceeds it. `.article-head` is excluded on purpose -- it
    // holds the headline and summary and is supposed to be tall.
    for (const [name, h] of Object.entries(heights)) {
      expect(h, `${name} wrapped onto a second line`).toBeLessThan(41);
    }
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

  test('the meta line leads with the source and the age', async ({ page }) => {
    // They moved down to the tags row when the card became three rows, and back
    // up again now that there is one line for everything. Same claim either
    // way: these are the items a reader reads rather than presses, so they come
    // first, and a missing date renders as nothing rather than "NaN".
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
    await expect(rows.nth(0).locator('.meta-source')).toHaveText('LA NACION');
    await expect(rows.nth(0).locator('.meta-age')).toHaveText('2h');
    await expect(rows.nth(1).locator('.meta-age')).toHaveText('now');
    // No date is common in feeds; it renders as nothing rather than "NaN".
    await expect(rows.nth(2).locator('.meta-age')).toHaveCount(0);

    // They lead the meta line, and it stays one line -- collapsing four rows
    // into one is the whole point, and it must not wrap back out.
    const meta = rows.nth(0).locator('.article-meta');
    await expect(meta.locator('.meta-source')).toHaveCount(1);
    // 48, not 30: the actions on this line stand 40px tall, so anything under
    // 48 is one line and only a wrap clears it.
    expect((await meta.boundingBox())!.height).toBeLessThan(48);
  });

  test('the source and age survive compact mode', async ({ page }) => {
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Compact list' }).click();
    await expect(page.locator('.meta-source').first()).toBeVisible();
    await expect(page.locator('.meta-age').first()).toBeVisible();
  });

});

test.describe('desktop keeps its layout', () => {
  test.skip(({ isMobile }) => isMobile, 'desktop-only');

  test('actions stay in a row and the sidebar is always visible', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');

    await expect(page.locator('.article-actions').first())
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

  test('the compact header stays compact, and its actions are named text', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // `.app-header` is the new top row -- hamburger, title, unread count, and
    // Refresh / Mark all read / Search as full-strength text on every width
    // (see redesign.spec.ts). Measured before the redesign: Refresh, Dismiss
    // all, What you missed and the field wrapped onto three rows -- a 173px
    // header on a 664px screen, a quarter of the viewport spent before the
    // first headline. This is the row that replaces that measurement.
    const header = (await page.locator('.app-header').boundingBox())!;
    expect(header.height).toBeLessThan(130);

    const actions = page.locator('.header-actions');
    for (const name of ['Refresh', 'Mark all read', 'Search']) {
      await expect(actions.getByText(name)).toBeVisible();
    }
  });

  test('every header action is a named control', async ({ page, isMobile }) => {
    // The legacy icon row this replaced lived for exactly one commit, stacked
    // under the compact header, rendering Refresh, Search and dismiss twice
    // each with two accessible names apiece. What is worth keeping from the
    // test that covered it is this: every action in the one remaining header
    // is reachable by the name a reader actually sees on it.
    const header = page.locator('.app-header');
    for (const name of ['Refresh', 'Mark all read', 'What you missed']) {
      await expect(header.getByRole('button', { name })).toBeVisible();
    }
    // Search is an action of the phone's header only: above 900px the field it
    // reveals is already open, so the button is hidden (and still rendered --
    // the "/" shortcut clicks it). The field is the named control there.
    if (isMobile) await expect(header.getByRole('button', { name: 'Search' })).toBeVisible();
    else await expect(page.locator('#search')).toBeVisible();
  });

  test('on a phone the search field is behind a button', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // It used to be squeezed into whatever width was left, which was 53px --
    // a field showing "Fi".
    await expect(page.locator('#search')).toBeHidden();
    await page.locator('.app-header').getByRole('button', { name: 'Search' }).click();

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
    // `.search-toggle` was an icon that existed only at phone width, then a
    // text action at every width. Task 7 settled it: on a desktop it toggled
    // nothing, because the field beside it is already open, so above 900px the
    // button is hidden -- and still rendered, because App.tsx's "/" shortcut
    // clicks it whenever the field itself cannot take focus.
    await expect(page.locator('.app-header').getByRole('button', { name: 'Search' }))
      .toBeHidden();
    await expect(page.locator('.app-header .search-toggle')).toHaveCount(1);
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
    // The photo sits to the *right* of the text in the redesign, where it used
    // to float on the left. The claim is unchanged: it must not take a row of
    // its own. Only the side it sits on moved.
    const thumb = (await page.locator('.article-row .article-thumb').first().boundingBox())!;
    expect(thumb.width).toBe(76);

    const title = (await page.locator('.article-row .article-title').first().boundingBox())!;
    expect(title.x, 'the headline was pushed under the photo')
      .toBeLessThan(thumb.x);
    expect(title.y, 'the headline starts level with the photo, not after it')
      .toBeLessThan(thumb.y + thumb.height);
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
    const narrow = (await page.locator('.article-row .article-title').first().boundingBox())!.width;

    await openDrawer(page);
    await page.getByRole('switch', { name: 'Show photos' }).click();

    await expect(thumb).toBeHidden();
    // The photo sits to the right now, so the headline reclaims the space by
    // growing wider rather than by moving left. The hole must not simply stay.
    const wide = (await page.locator('.article-row .article-title').first().boundingBox())!.width;
    expect(wide).toBeGreaterThan(narrow);
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

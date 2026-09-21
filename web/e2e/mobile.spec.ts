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
    // This suite's default fixture carries no thumbnail (`article()` defaults
    // `thumbnail_url: null`), so there is no float here for the box to
    // disagree with the text about: `.article-title`'s bounding box is the
    // rendered width, exactly as it was when `.article-text` was the sole
    // flex child. The float-vs-box distinction that forced the other two
    // tests in `describe('photos')` onto `Range.getClientRects()` does not
    // apply to this one -- there is nothing here for it to apply to.
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
    // Guarded first: `g()` answers 0 for a node that is not there, and 0 is
    // under every threshold below -- so a renamed class would empty this test
    // rather than fail it.
    for (const [name, h] of Object.entries(heights)) {
      expect(h, `${name} is missing, so this test is asserting nothing`)
        .toBeGreaterThan(0);
    }
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

  test('compact mode drops the hidden-reason with the summary', async ({ page }) => {
    // Compact hid `.article-summary` and nothing else, so on the Hidden list it
    // traded one paragraph of prose for another -- the reason is longer than
    // some summaries. It is still on the score's `title` attribute, so nothing
    // is lost by dropping it from the row.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [article(1, {
        hidden: true,
        score_reason: 'No stated interest in municipal parking policy.',
      })],
      next_offset: null, diagnosis: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await expect(page.locator('.hidden-reason')).toBeVisible();

    await openDrawer(page);
    await page.getByRole('switch', { name: 'Compact list' }).click();
    await expect(page.locator('.hidden-reason')).toBeHidden();
    // Still reachable, just not as a second paragraph.
    await expect(page.locator('.meta-score').first())
      .toHaveAttribute('title', 'No stated interest in municipal parking policy.');
  });

  test('compact mode keeps the meta line below the photo, not beside it', async ({ page }) => {
    // Compact hides the summary, so only a single-line headline sits next to
    // the photo -- shorter than the 76px float, which makes the float the
    // taller thing in `.article-head`. This is the case the plan for this
    // change called most likely to look wrong: without `.article-head`
    // containing the float (`display: flow-root`), the row's own box would
    // collapse around the short text and `.article-meta` -- score, source,
    // Save/Up/Down -- would ride up beside the photo instead of clearing it.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [article(1, { thumbnail_url: 'https://example.com/thumb.jpg' })],
      next_offset: null, diagnosis: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Compact list' }).click();
    await expect(page.locator('.article-summary')).toBeHidden();

    const thumb = (await page.locator('.article-row .article-thumb').first().boundingBox())!;
    const meta = (await page.locator('.article-row .article-meta').first().boundingBox())!;
    expect(meta.y, 'the meta line rode up beside the photo instead of clearing it')
      .toBeGreaterThanOrEqual(thumb.y + thumb.height - 1);
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

  test('the list is tighter than a screen-and-a-half per story', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // Whitespace is still the only thing dividing the stories -- no dividers,
    // no row tints -- and this batch halves it again: 7px, from 14. The
    // previous batch drew 14 as the floor with the card's own spacing held
    // fixed; halving that too (`.article-row`'s padding and gap, and
    // `.article-text`'s gap) is what makes another halving legal -- the
    // ratios below are still 3.0:1 in both densities, so this is the rhythm
    // scaling down, not the floor being spent.
    await expect(page.locator('#article-list')).toHaveCSS('row-gap', '7px');
    // Row height *plus* the gap: a story costs a reader both, and dividing by
    // the row alone counted a list with no space between the cards. Halving
    // the rhythm only shrinks the gap term, so this comfortably clears four.
    const perScreen = await page.evaluate(() => {
      const row = (document.querySelector('.article-row') as HTMLElement)
        .getBoundingClientRect().height;
      const gap = parseFloat(getComputedStyle(document.querySelector('#article-list')!).rowGap);
      return window.innerHeight / (row + gap);
    });
    expect(perScreen, 'more than four stories must fit a screen').toBeGreaterThan(4);

    // Visual separation, not the CSS gap. A bounding box includes the row's own
    // padding, so `next.top - prev.bottom` is the gap alone and ignores the 4px
    // each row adds on both sides -- it understated the real separation by 8px
    // and would have failed a layout that is in fact well spaced. Against it,
    // the card's own largest internal gap: the 5px between the story and its
    // meta line. The 4px inside `.article-text` is the wrong comparison --
    // compact hides the summary, so in that density it spans nothing at all,
    // and measuring against it is how compact was scored 3.75:1 while actually
    // sitting at 2.6.
    const measure = () => page.evaluate(() => {
      const rows = [...document.querySelectorAll('.article-row')] as HTMLElement[];
      const pad = (el: HTMLElement) =>
        parseFloat(getComputedStyle(el).paddingTop) + parseFloat(getComputedStyle(el).paddingBottom);
      const between = rows.slice(1).map((r, i) => {
        const gap = r.getBoundingClientRect().top - rows[i].getBoundingClientRect().bottom;
        return gap + pad(r) / 2 + pad(rows[i]) / 2;
      });
      return { sep: Math.min(...between), inner: parseFloat(getComputedStyle(rows[0]).rowGap) };
    });

    // Both densities, because only one of them was ever measured. Compact drops
    // the summary and 2px of row padding with it; at a floor of 24 it passed at
    // 26px and 2.6:1 -- tighter than the comfortable list this branch calls the
    // floor -- and the test could not see it.
    for (const density of ['comfortable', 'compact'] as const) {
      if (density === 'compact') {
        await openDrawer(page);
        await page.getByRole('switch', { name: 'Compact list' }).click();
        await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');
        await page.locator('.drawer-scrim').click({ position: { x: 340, y: 40 } });
        await expect(page.locator('.sidebar.open')).toHaveCount(0);
      }
      const { sep, inner } = await measure();
      expect(sep, `${density}: two stories sit closer than 15px apart`)
        .toBeGreaterThanOrEqual(15);
      expect(sep / inner,
        `${density}: the space between two stories is not clearly more than the space inside one`)
        .toBeGreaterThanOrEqual(3);
    }
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

  test('every control in the reader top bar clears the WCAG floor', async ({ page }) => {
    // The sweep at the top of this file measures `.article-actions .action`
    // and nothing else, so it could not see the one screen a reader spends the
    // most time on. When the reader bar moved onto `.header-action` -- which
    // sets `padding: 0` -- the "Open in browser" link kept its 13px text and
    // lost every scrap of box around it: 95.4 x 19.5, against a Back button
    // standing 40px because it is a <button> and the coarse-pointer floor
    // catches those. An <a> matches nothing in that selector list.
    //
    // Swept, not named: a third control in this bar must earn a target too.
    await page.locator('.article-title').first().click();
    const nav = page.getByRole('dialog').locator('.modal-nav');
    await expect(nav).toBeVisible();
    const controls = await nav.locator('button, a, [role="button"]').all();
    expect(controls.length, 'no controls found -- this test is asserting nothing')
      .toBeGreaterThan(1);
    for (const control of controls) {
      const box = (await control.boundingBox())!;
      const name = (await control.textContent())?.trim() ?? '';
      expect(Math.min(box.width, box.height), `"${name}" is ${box.width}x${box.height}`)
        .toBeGreaterThanOrEqual(24);
    }
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

  test('the header row fits on one line, and the count never touches the actions',
    async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The sticky-header fix moved `.drawer-toggle` out of `position: fixed` and
    // into the header's flow, which was right -- but a fixed element is out of
    // flow and contributes no width, and the in-flow button costs ~12px the row
    // did not have. At 390px "All feeds" wrapped to two lines (51px against a
    // 25.5px line-height), "Mark all read" wrapped with it, and `.unread-count`
    // ended at exactly the x `.header-actions` began: "139Refresh" as one
    // string, because `justify-content: space-between` distributes leftover
    // space and there was none left.
    //
    // Asserted as the goal and not the mechanism: line boxes against the
    // element's own line-height, and a gap greater than zero. A pixel-width
    // assertion here would fail the next time the type changes; these two hold
    // whatever the fix is and whatever the font is.
    const oneLine = async (selector: string) => {
      const el = page.locator(selector);
      await expect(el).toBeVisible();
      return el.evaluate((node) => {
        const cs = getComputedStyle(node);
        // The text's own line boxes, not the button's box: the coarse-pointer
        // tap floor stands every action at 40px tall whether it wrapped or not.
        const range = document.createRange();
        range.selectNodeContents(node);
        const lh = cs.lineHeight === 'normal'
          ? parseFloat(cs.fontSize) * 1.4
          : parseFloat(cs.lineHeight);
        return { text: node.textContent?.trim() ?? '', height: range.getBoundingClientRect().height, lineHeight: lh };
      });
    };

    const fits = async () => {
      for (const selector of ['.header-name', '#poll-btn', '#dismiss-all-btn', '.search-toggle']) {
        const { text, height, lineHeight } = await oneLine(selector);
        expect(height, `"${text}" (${selector}) wrapped: ${height}px of ${lineHeight}px line-height`)
          .toBeLessThanOrEqual(lineHeight * 1.4);
      }

      const count = (await page.locator('.unread-count').boundingBox())!;
      const actionsBox = (await page.locator('.header-actions').boundingBox())!;
      expect(actionsBox.x - (count.x + count.width),
        'the unread count is flush against the first action').toBeGreaterThan(0);

      // One line and no overflow was the whole assertion, and both were true
      // at 375px while the title read "All fee...". `.header-name` ellipsises
      // rather than wrapping, and it is the only flexible item in the row, so
      // it absorbs any shortfall in silence: nothing wraps, `document`'s
      // scrollWidth never exceeds the viewport, and the feed name is the thing
      // that pays. Reading the element's own overflow is what sees it.
      const title = await page.locator('.header-name').evaluate((node) => ({
        text: node.textContent ?? '',
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
      }));
      expect(title.scrollWidth,
        `"${title.text}" is ellipsised: ${title.scrollWidth}px of name in ${title.clientWidth}px of box`)
        .toBeLessThanOrEqual(title.clientWidth);
    };

    await fits();

    // 375, not only the project's 390. The iPhone SE 2/3, the 8 and the 13
    // mini all render 375 and all three are current; at that width the header
    // had 15px less than "All feeds" needs.
    await page.setViewportSize({ width: 375, height: 667 });
    await expect(page.locator('.app-header')).toBeVisible();
    await fits();
  });

  test('a scroll the browser performs lands clear of the pinned header', async ({ page }) => {
    // The header is `position: sticky` and opaque, so it covers whatever is
    // under it. Find-in-page, `scrollIntoView`, `scrollIntoViewIfNeeded` and a
    // fragment jump all scroll the *page*, not the app, and none of them knows
    // the top ~71px is spoken for -- they put their target at y=0 and the
    // header draws over it. `scroll-padding-top` on the scroll port is what
    // tells them, and it has been missing since the header was pinned.
    const header = (await page.locator('.app-header').boundingBox())!;
    // Not the last row: at the foot of the document there is nothing left to
    // scroll, the target stops short of the top on its own, and the assertion
    // passes whatever the padding is. A row in the middle is the one that
    // actually gets put at the top.
    const row = page.locator('.article-row').nth(3);
    await row.evaluate((el) => el.scrollIntoView());
    const box = (await row.boundingBox())!;
    expect(box.y, `the row landed ${header.height - box.y}px under the header`)
      .toBeGreaterThanOrEqual(header.height);
  });

  test('every header action is a named control', async ({ page, isMobile }) => {
    // The legacy icon row this replaced lived for exactly one commit, stacked
    // under the compact header, rendering Refresh, Search and dismiss twice
    // each with two accessible names apiece. What is worth keeping from the
    // test that covered it is this: every action in the one remaining header
    // is reachable by the name a reader actually sees on it.
    const header = page.locator('.app-header');
    for (const name of ['Refresh', 'Mark all read']) {
      await expect(header.getByRole('button', { name })).toBeVisible();
    }
    // The briefing is a header action on a desktop and the strip's "Read"
    // button on a phone. That is the design's split, and it is load-bearing:
    // as a fourth action at 390px it left no gap between the unread count and
    // Refresh, wrapped every label, and stood the header up at 127px.
    const briefing = header.getByRole('button', { name: 'What you missed' });
    if (isMobile) {
      await expect(briefing).toBeHidden();
      await expect(page.locator('.missed-cta')).toBeVisible();
    } else {
      await expect(briefing).toBeVisible();
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
    // The feed list is the drawer's first group, so with thirty feeds
    // everything below it is off-screen until you scroll. What matters is that
    // scrolling reaches them: an earlier version made the whole sidebar
    // `overflow: hidden` to pin a footer that no longer exists, which would
    // leave the settings block and the footer links unreachable on a phone --
    // the one place nothing else opens them.
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

    // Was the `.sidebar-section` labelled "Admin". The sections are gone and
    // the admin links moved into the drawer's footer, which is now the last
    // thing in the column and so the thing furthest out of reach.
    await page.locator('.drawer-footer').scrollIntoViewIfNeeded();

    const vp = page.viewportSize()!;
    for (const name of ['Sign out', 'Ollama log']) {
      const box = (await page.getByRole('button', { name }).boundingBox())!;
      expect(box.y + box.height, `${name} was not reachable`).toBeLessThanOrEqual(vp.height);
      expect(box.y, `${name} was above the viewport`).toBeGreaterThanOrEqual(0);
    }
    await expect(page.getByRole('radiogroup', { name: 'Theme' })).toBeAttached();
  });

  test('the top bar stays on screen at the bottom of the list', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // Mark all read is a header action, and the reader reaches for it after
    // reading the last story on screen -- which is exactly where an unpinned
    // header is furthest away. It was not sticky because the hamburger inside
    // it was `position: fixed` to outrank the open drawer; the scrim closes
    // the drawer now, so the header can pin and the hamburger can ride with it.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const header = page.locator('.app-header');
    await expect(header).toBeInViewport();
    expect((await header.boundingBox())!.y).toBeLessThanOrEqual(1);
    await expect(header.getByRole('button', { name: 'Mark all read' })).toBeInViewport();
  });

  test('the menu button never sits on top of a headline', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // It was fixed at top:58px/left:24px with no background, so once the
    // header scrolled past, two ink bars floated over the first story's
    // headline. In the header's flow it cannot overlap anything below it.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const toggle = (await page.locator('.drawer-toggle').boundingBox())!;
    const header = (await page.locator('.app-header').boundingBox())!;
    expect(toggle.y + toggle.height, 'the toggle escaped the header')
      .toBeLessThanOrEqual(header.y + header.height + 1);

    // And the element under the first headline's top-left corner is the
    // headline, not the button.
    const title = (await page.locator('.article-title').first().boundingBox())!;
    const onTop = await page.evaluate(
      ([x, y]) => (document.elementFromPoint(x, y) as HTMLElement)?.className ?? '',
      [title.x + 4, title.y + 4] as const,
    );
    expect(onTop).not.toContain('drawer-toggle');
  });

  test('the drawer covers the header, and the scrim closes it', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The header is sticky now, so it has a stacking context: it must sit
    // *under* the scrim (18) and the drawer (25), and the scrim -- not the
    // hamburger buried beneath it -- is what shuts the drawer again.
    await openDrawer(page);
    await expect(page.locator('.sidebar.open')).toHaveCount(1);
    // Not the top-left corner: the scrim spans the viewport, so its own (5, 5)
    // is underneath the 260px drawer. Click to the right of the drawer's edge.
    await page.locator('.drawer-scrim').click({ position: { x: 340, y: 40 } });
    await expect(page.locator('.sidebar.open')).toHaveCount(0);
  });

  test('the switches are pills, and still clear the tap floor', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // `@media (pointer: coarse)` put a 40px floor on every button without
    // `.pill`. A switch is a track: 42 wide, floored to 40 tall, with a 999px
    // radius, it rendered as a circle on every phone -- and only on a phone,
    // which is why it lived this long. The drawn size comes back and the tap
    // target moves to a pseudo-element.
    await openDrawer(page);
    const toggle = page.getByRole('switch', { name: 'Compact list' });
    const box = (await toggle.boundingBox())!;
    expect(box.height, 'the track grew to meet the tap floor').toBeLessThanOrEqual(28);
    expect(box.width / box.height, 'a switch is wider than it is tall')
      .toBeGreaterThan(1.4);

    // The target is still there, it is just not the painted box -- so probe
    // the hit region rather than the declaration that draws it. Reading
    // `getComputedStyle(el, '::after')`'s insets and adding them to the track
    // asserts the mechanism: it stays green if `.toggle` loses
    // `position: relative`, at which point those same insets resolve against
    // some ancestor's padding box and the 44px lands somewhere else entirely.
    // On screen first: the drawer is taller than an iPhone, this row sits
    // ~980px down it, and `elementFromPoint` answers null for anything past
    // the fold. The computed-style probe this replaces never needed the
    // control to be visible, which is part of how it drifted off the goal.
    await toggle.scrollIntoViewIfNeeded();
    const onScreen = (await toggle.boundingBox())!;
    const above = { x: onScreen.x + onScreen.width / 2, y: onScreen.y - 8 };
    const hit = await page.evaluate(
      (p) => document.elementFromPoint(p.x, p.y)?.getAttribute('aria-label'),
      above,
    );
    expect(hit, '8px above the track is not the switch').toBe('Compact list');

    // And it is a working target, not merely the topmost element there.
    const before = await toggle.getAttribute('aria-checked');
    await page.mouse.click(above.x, above.y);
    await expect(toggle).not.toHaveAttribute('aria-checked', before!);
  });

  test('the segmented controls do not stand 40px tall', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // Same floor, same shape problem, one step smaller: Sort and Theme are
    // two- and three-position radiogroups, not primary actions.
    await openDrawer(page);
    const segment = page.getByRole('radiogroup', { name: 'Sort' })
      .getByRole('radio').first();
    const box = (await segment.boundingBox())!;
    expect(box.height).toBeLessThanOrEqual(34);
    // WCAG 2.5.8 is 24px; this must stay above it.
    expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(24);
  });

  test('the headline is a headline, not a heading', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // 19px on a 390pt screen sat a headline within a point of the body text
    // and, at three lines, set the height of every card. 15/400 keeps the
    // hierarchy against the 13px summary through size and colour rather than
    // weight, and buys back a story a screen. The desktop keeps 17 -- it has
    // a 760px measure to fill. This test owns the sizes and the step between
    // them; 'the list carries its hierarchy in colour too' owns the colour.
    const title = page.locator('.article-title').first();
    await expect(title).toHaveCSS('font-size', '15px');
    // The headline carried weight 600, which on a list of forty stories is a
    // wall of bold with nothing standing out of it.
    await expect(title).toHaveCSS('font-weight', '400');
    const summary = page.locator('.article-summary').first();
    await expect(summary).toHaveCSS('font-size', '13px');
    const [t, s] = [
      parseFloat(await title.evaluate((el) => getComputedStyle(el).fontSize)),
      parseFloat(await summary.evaluate((el) => getComputedStyle(el).fontSize)),
    ];
    // A step of 2px, stated as a floor rather than as the pair of exact sizes
    // above it: this is the claim that has to survive either size moving, and
    // it is the one that was relaxed to `> s` when the headline came down to
    // 15 -- which a summary back at 14px would have passed.
    expect(t, 'the headline must still outrank the summary').toBeGreaterThanOrEqual(s + 2);
  });

  test('the tags switch shows and hides the topic, on a phone too', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The tag was desktop-only: `display: none` at base, `inline` inside the
    // 900px block, because the meta line is one line on a phone and the tag is
    // the item that wraps it. The preference replaces that breakpoint, so the
    // switch means the same thing on both devices -- and defaults off, which
    // is what a phone shows today.
    await expect(page.locator('.meta-tag').first()).toBeHidden();

    await openDrawer(page);
    const tags = page.getByRole('switch', { name: 'Show tags' });
    await expect(tags).toHaveAttribute('aria-checked', 'false');
    await tags.click();
    await page.locator('.drawer-scrim').click({ position: { x: 340, y: 40 } });

    await expect(page.locator('.meta-tag').first()).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-tags', 'on');
    // And it must not cost the single meta line. 48, the same floor the
    // source-and-age test uses: the actions stand 40px tall, so anything
    // under 48 is one line and only a wrap clears it.
    const meta = page.locator('.article-meta').first();
    expect((await meta.boundingBox())!.height).toBeLessThan(48);
  });

  test('the tags choice survives a reload', async ({ page }) => {
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Show tags' }).click();
    await page.reload();
    await page.waitForSelector('.article-row');
    await expect(page.locator('html')).toHaveAttribute('data-tags', 'on');
    await openDrawer(page);
    await expect(page.getByRole('switch', { name: 'Show tags' }))
      .toHaveAttribute('aria-checked', 'true');
  });

  test('a long tag is capped rather than allowed to wrap the line', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The 13ch cap was dropped with the tag row that needed it. The tag is
    // back at phone width, so the cap comes back with it.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [article(1, { topics: ['campeonato-brasileiro-serie-a'] })],
      next_offset: null, diagnosis: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await openDrawer(page);
    await page.getByRole('switch', { name: 'Show tags' }).click();
    await page.locator('.drawer-scrim').click({ position: { x: 340, y: 40 } });

    const tag = (await page.locator('.meta-tag').first().boundingBox())!;
    const viewport = page.viewportSize()!.width;
    expect(tag.width, 'the tag took the whole meta line').toBeLessThan(viewport * 0.4);
    expect((await page.locator('.article-meta').first().boundingBox())!.height)
      .toBeLessThan(48);
  });

  test('the list carries its hierarchy in colour too', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The sizes and the 2px step between them are asserted once, in 'the
    // headline is a headline, not a heading'; this test used to restate both
    // and then add `expect(t).toBeGreaterThan(s)` under two exact
    // `toHaveCSS` assertions that had already fixed t and s. What is only
    // claimed here is the colour: with the weight gone, 15px `--color-ink`
    // over a 13px `--color-ink-body` summary is half of what separates a
    // headline from its own standfirst, and two pixels is the other half.
    const title = page.locator('.article-title').first();
    const summary = page.locator('.article-summary').first();
    const [tc, sc] = [
      await title.evaluate((el) => getComputedStyle(el).color),
      await summary.evaluate((el) => getComputedStyle(el).color),
    ];
    expect(tc, 'the headline and the summary must not share a colour').not.toBe(sc);
  });

  test('a read story is never bolder than an unread one', async ({ page }) => {
    // `.article-row.read .article-title` set `font-weight: 500` to lighten a
    // read headline against an unread 600. With unread at 400 that rule
    // inverts and read becomes the boldest thing on the screen. Colour is what
    // carries read state.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [
        article(1, { state: { read: true, saved: false, dismissed: false, opinion: null } }),
        article(2, { state: { read: false, saved: false, dismissed: false, opinion: null } }),
      ],
      next_offset: null, diagnosis: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');

    const weight = (sel: string) => page.locator(sel).evaluate(
      (el) => parseInt(getComputedStyle(el).fontWeight, 10));
    const read = await weight('.article-row.read .article-title');
    const unread = await weight('.article-row:not(.read) .article-title');
    expect(read, 'a read headline outweighs an unread one').toBeLessThanOrEqual(unread);
    // And read state is still visible, just not through weight.
    const colours = await Promise.all(['.article-row.read .article-title',
                                       '.article-row:not(.read) .article-title']
      .map((s) => page.locator(s).evaluate((el) => getComputedStyle(el).color)));
    expect(colours[0]).not.toBe(colours[1]);
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
    //
    // Under a float `.article-title`'s own box always spans the full column
    // width, no matter where its text actually renders -- a float narrows
    // line boxes, not the element box that contains them -- so a bounding-box
    // comparison against the thumb no longer proves anything a reader would
    // notice. This measures the *rendered first line* instead, with
    // `Range.getClientRects()`.
    const thumb = (await page.locator('.article-row .article-thumb').first().boundingBox())!;
    expect(thumb.width).toBe(76);
    // Still on the right: nothing sits further right in the row than it does.
    const row = (await page.locator('.article-row').first().boundingBox())!;
    expect(thumb.x, 'the photo moved off the right side of the card')
      .toBeGreaterThan(row.x + row.width / 2);

    const firstLine = await page.locator('.article-row .article-title').first().evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      const r = range.getClientRects()[0];
      return { x: r.x, y: r.y, right: r.right };
    });
    expect(firstLine.x, 'the headline was pushed under the photo')
      .toBeLessThan(thumb.x);
    expect(firstLine.y, 'the headline starts level with the photo, not after it')
      .toBeLessThan(thumb.y + thumb.height);
    expect(firstLine.right, 'the first line runs into the photo instead of stopping beside it')
      .toBeLessThanOrEqual(thumb.x + 1);
  });

  test('a headline and summary long enough to run past the photo wrap under it', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only');
    // The reader's actual complaint: a flex row leaves the space below a
    // short 76px photo empty once the text runs taller than it. Wrapping
    // means a later line of text starts left of the photo *and* runs under
    // it -- the text fills the column instead of stopping at a boundary a
    // float doesn't have. An element's bounding box can't show this: under a
    // float the box always spans the full column regardless of where the
    // glyphs are, so this measures the real text with
    // `Range.getClientRects()`.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [article(1, {
        thumbnail_url: PIXEL,
        title: 'A headline on its own long enough to run past the bottom edge of a seventy-six pixel photo on a phone screen',
        summary: 'And a summary long enough that, together with the headline above it, the text runs well past the photo and has to fill the rest of the row by itself, line after line, exactly the way the reader asked for it to.',
      })],
      next_offset: null, diagnosis: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');

    const thumb = (await page.locator('.article-row .article-thumb').first().boundingBox())!;

    const lineRects = async (selector: string) => page.locator(selector).first().evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      return [...range.getClientRects()].map((r) => ({ x: r.x, y: r.y, right: r.right, width: r.width }));
    });
    // Both elements: the headline alone is long enough to run past the
    // photo's 76px height, so its own later lines -- and the whole summary
    // after it -- are the ones that should be running the full column width.
    const rects = [...await lineRects('.article-row .article-title'), ...await lineRects('.article-row .article-summary')];

    const besidePhoto = rects.filter((r) => r.y < thumb.y + thumb.height - 1);
    const belowPhoto = rects.filter((r) => r.y >= thumb.y + thumb.height - 1);
    expect(besidePhoto.length, 'no line rendered beside the photo -- nothing to compare the wrapped width against')
      .toBeGreaterThan(0);
    expect(belowPhoto.length, 'no line rendered below the photo -- the fixture text is not long enough')
      .toBeGreaterThan(0);
    // Every line below the photo starts at the text column's left edge --
    // there is no reserved column to indent around any more.
    for (const r of belowPhoto) {
      expect(r.x, 'a line below the photo must start at the column edge, not indented for a photo that is no longer beside it')
        .toBeLessThan(thumb.x);
    }
    // And at least one of them is meaningfully wider than any line that was
    // still narrowed beside the photo -- comparing rendered widths against
    // each other, not against a fixed pixel target, so this holds regardless
    // of exactly where a particular engine's word-wrap happens to break a
    // line. A fixed target (e.g. "within 5px of the photo's far edge") is
    // exactly the kind of assertion natural word-wrapping trailing slack
    // makes flaky across engines with different font metrics.
    const widestBeside = Math.max(...besidePhoto.map((r) => r.width));
    const widestBelow = Math.max(...belowPhoto.map((r) => r.width));
    expect(widestBelow, 'no line below the photo is meaningfully wider than one still narrowed beside it -- the text never reclaimed the column')
      .toBeGreaterThan(widestBeside + 40);
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
    //
    // `.article-title`'s own box spans the full column width whether or not
    // the photo is even there -- a block box's width ignores floats
    // regardless of their presence -- so comparing the box before and after
    // no longer proves the text reflowed at all: it would report an
    // unchanged width and this test would start failing on a photo that
    // really did give the width back. This compares the *rendered first
    // line*, measured with `Range.getClientRects()`, which the float
    // actually does narrow -- but only if the headline is long enough to
    // still be wrapping once the photo is gone. The default fixture's
    // headline is short enough to fit on one line on the wide desktop
    // column even with the photo taking a bite out of it, so on that
    // project the two states rendered an identical, unwrapped first line
    // and this test passed for the wrong reason. A headline long enough to
    // wrap at both widths makes the comparison mean something everywhere.
    await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
      articles: [article(1, {
        thumbnail_url: PIXEL,
        title: 'This particular headline is deliberately written long enough that it must wrap onto more than one line whether or not the photo is still there beside it, on a phone or on the wider desktop column.',
      })],
      next_offset: null, diagnosis: null,
    } }));
    await page.reload();
    await page.waitForSelector('.article-row');

    const thumb = page.locator('.article-row .article-thumb').first();
    await expect(thumb).toBeVisible();
    const firstLineWidth = () => page.locator('.article-row .article-title').first().evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      return range.getClientRects()[0].width;
    });
    const narrow = await firstLineWidth();

    await openDrawer(page);
    await page.getByRole('switch', { name: 'Show photos' }).click();

    await expect(thumb).toBeHidden();
    // The photo sits to the right now, so the headline reclaims the space by
    // growing wider rather than by moving left. The hole must not simply stay.
    const wide = await firstLineWidth();
    expect(wide).toBeGreaterThan(narrow);

    // No float, no reserved column: the text fills the row's own width, not
    // a width still leaving room for the photo that is no longer there.
    const row = (await page.locator('.article-row').first().boundingBox())!;
    const title = (await page.locator('.article-row .article-title').first().boundingBox())!;
    expect(title.x, 'the headline left a leftover left margin with photos off')
      .toBeCloseTo(row.x, 0);
    expect(title.x + title.width, 'the headline left a reserved gap on the right with photos off')
      .toBeGreaterThan(row.x + row.width - 2);
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
    // it -- it is not a dialog. The scrim, not the hamburger: the toggle rides
    // in the sticky header now and the open drawer covers it. On a desktop the
    // sidebar is in flow, nothing opened it, and the scrim has no box to click.
    const scrim = page.locator('.drawer-scrim');
    if (await scrim.isVisible()) await scrim.click({ position: { x: 340, y: 40 } });
    await expect(page.locator('.sidebar.open')).toHaveCount(0);

    await page.locator('.article-title').first().click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByRole('dialog').locator('.modal-lead')).toBeHidden();
  });
});

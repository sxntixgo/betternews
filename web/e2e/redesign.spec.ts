import { expect, test } from '@playwright/test';
import { article, mockApi, openDrawer, signedIn, signInFlow } from './fixtures';

test.describe('story row', () => {
  test('is one meta+actions line, not four rows', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const row = page.locator('#card-1');
    await expect(row.locator('.article-meta')).toHaveCount(1);
    // The pill, the topic chips and the Open link were the other three rows.
    await expect(row.locator('.score-badge')).toHaveCount(0);
    await expect(row.locator('.topic-chips')).toHaveCount(0);
  });

  test('shows the score as a bare number in gold, no percent sign', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    // fixtures' article() scores 0.8.
    await expect(page.locator('#card-1 .meta-score')).toHaveText('80');
  });

  test('actions are text labels, never emoji', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const actions = page.locator('#card-1 .article-actions');
    await expect(actions.getByRole('button', { name: 'Save' })).toBeVisible();
    await expect(actions.getByRole('button', { name: 'Up' })).toBeVisible();
    await expect(actions.getByRole('button', { name: 'Down' })).toBeVisible();
    await expect(actions).not.toContainText(/[👍👎★☆]/);
  });

  test('saving switches the label to its active form', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.locator('#card-1 .article-actions').getByRole('button', { name: 'Save' }).click();
    await expect(
      page.locator('#card-1 .article-actions').getByRole('button', { name: 'Saved' }),
    ).toBeVisible();
  });

  test('duplicate count fills the slot the mock labelled comments', async ({ page }) => {
    await signedIn(page);
    await mockApi(page, [article(1, { duplicate_count: 3 })]);
    await page.goto('/');
    await expect(page.locator('#card-1 .meta-dupes')).toHaveText('3');
  });
});

test.describe('list rhythm', () => {
  test('stories are separated by space, not rules or tints', async ({ page, isMobile }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const row = page.locator('#card-1');
    const styles = await row.evaluate((el) => {
      const cs = getComputedStyle(el);
      return {
        bg: cs.backgroundColor,
        borderBottom: cs.borderBottomWidth,
        gap: getComputedStyle(el.parentElement as HTMLElement).rowGap,
      };
    });
    expect(styles.bg).toBe('rgba(0, 0, 0, 0)');
    expect(styles.borderBottom).toBe('0px');
    // The rhythm widens with the measure -- 34px on a phone, 40px above 900px.
    // The claim is what does the separating, and at either width it is space.
    expect(styles.gap).toBe(isMobile ? '34px' : '40px');
  });

  test('a read story is dimmed rather than tinted', async ({ page }) => {
    await signedIn(page);
    await mockApi(page, [article(1, { state: { read: true, saved: false, dismissed: false, opinion: null } })]);
    await page.goto('/');
    const row = page.locator('#card-1');
    await expect(row).toHaveClass(/read/);
    expect(await row.evaluate((el) => getComputedStyle(el).opacity)).toBe('0.55');
  });
});

test.describe('mobile header', () => {
  test('carries every action as full-strength text', async ({ page, isMobile }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const actions = page.locator('.header-actions');
    // Three at every width. The briefing opener moved up here when the legacy
    // icon row was removed, rather than being lost with it.
    for (const name of ['Refresh', 'Mark all read', 'What you missed']) {
      await expect(actions.getByRole('button', { name })).toBeVisible();
    }
    // Search is the fourth on a phone, where it reveals the field. Above 900px
    // the field is already open beside it, so the button is hidden -- see
    // "the toolbar drops Search" below, which also holds it in the DOM.
    const search = actions.getByRole('button', { name: 'Search' });
    if (isMobile) await expect(search).toBeVisible();
    else await expect(search).toBeHidden();
  });

  test('the missed strip is the first list item and is not sticky', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const strip = page.locator('.missed-strip');
    await expect(strip).toBeVisible();
    expect(await strip.evaluate((el) => getComputedStyle(el).position)).toBe('static');
    await expect(strip.getByRole('button', { name: 'Read' })).toBeVisible();
  });

  test('the subtitle reports the count and label from digest/meta, not the raw unread count', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    // fixtures' DIGEST_META: story_count 32, since_label 'Friday', read_minutes 2.
    // FEEDS.unread is 139 -- if this read that instead, it would say so.
    await expect(page.locator('.missed-sub')).toHaveText('32 stories since Friday · 2 min summary');
  });
});

/**
 * The desktop half of the redesign.
 *
 * Scoped by `isMobile` rather than by a `test.use({ viewport })` override, so
 * these run on the project whose metrics they describe instead of forcing an
 * iPhone to 1280px and asserting desktop CSS on it. The mirror of each claim --
 * that everything here collapses again below 900px -- is the phone-only block
 * underneath.
 */
test.describe('desktop layout', () => {
  test.skip(({ isMobile }) => isMobile, 'desktop only');

  test('the list is held to a 760px measure with a 40px rhythm', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    // `#article-list`, an id: App.tsx has never rendered a `.article-list`.
    const list = page.locator('#article-list');
    const box = (await list.boundingBox())!;
    expect(box.width).toBeLessThanOrEqual(760);
    expect(await list.evaluate((el) => getComputedStyle(el).rowGap)).toBe('40px');
  });

  test('the thumbnail is 104 x 78 on desktop', async ({ page }) => {
    await signedIn(page);
    await mockApi(page, [article(1, { thumbnail_url: 'https://example.com/p.jpg' })]);
    await page.goto('/');
    const box = (await page.locator('#card-1 .article-thumb').boundingBox())!;
    expect(Math.round(box.width)).toBe(104);
    expect(Math.round(box.height)).toBe(78);
  });

  test('the filter field is an underline, not a bordered box', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    // There is one filter field and it is the one the app already had. A second
    // one would be Task 6's mistake again -- that task shipped a new header
    // over the old toolbar and rendered three controls twice.
    await expect(page.locator('input[type="search"]')).toHaveCount(1);
    const cs = await page.locator('#search').evaluate((el) => {
      const s = getComputedStyle(el);
      return { top: s.borderTopWidth, bottom: s.borderBottomWidth };
    });
    expect(cs.top).toBe('0px');
    expect(cs.bottom).toBe('1px');
  });

  test('the toolbar drops Search, because the field beside it is already open', async ({
    page,
  }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await expect(page.locator('#search')).toBeVisible();
    // Hidden by CSS and still rendered: App.tsx's "/" shortcut clicks this
    // button when the field cannot take focus, so it must stay in the DOM.
    await expect(page.locator('.search-toggle')).toHaveCount(1);
    await expect(page.locator('.search-toggle')).toBeHidden();
  });

  test('the card offers Open, and it goes to the article in a new tab', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const open = page.locator('#card-1 .action-open');
    await expect(open).toBeVisible();
    await expect(open).toHaveAttribute('href', 'https://example.com/1');
    await expect(open).toHaveAttribute('target', '_blank');
    await expect(open).toHaveAttribute('rel', /noopener/);
  });

  test('one topic comes back to the meta line, as plain text', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    // One, not the chip row the four-row card carried: fixtures' article has
    // two topics and only the first is shown.
    await expect(page.locator('#card-1 .meta-tag')).toHaveText('economy');
    // One, and only one. The fixture carries two topics; asserting the count
    // is what proves the second is dropped. Checking that `.topic-chip` is
    // absent proved nothing -- that class exists nowhere in the app, so the
    // assertion was true before the feature was written and would stay true
    // if every tag came back.
    await expect(page.locator('#card-1 .meta-tag')).toHaveCount(1);
  });

  test('the topic filters the list, and does not also open the reader', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const asked: string[] = [];
    page.on('request', (r) => {
      if (r.url().includes('/api/v1/articles?')) asked.push(r.url());
    });
    await page.locator('#card-1 .meta-tag').click();
    await expect.poll(() => asked.some((u) => u.includes('topic=economy'))).toBe(true);
    // The card opens the reader when clicked; a control on it must not.
    await expect(page.getByRole('dialog')).toBeHidden();
  });
});

test.describe('below 900px the desktop layout collapses', () => {
  test.skip(({ isMobile }) => !isMobile, 'phone only');

  test('the phone keeps its own metrics and none of the desktop extras', async ({ page }) => {
    await signedIn(page);
    await mockApi(page, [article(1, { thumbnail_url: 'https://example.com/p.jpg' })]);
    await page.goto('/');
    const thumb = (await page.locator('#card-1 .article-thumb').boundingBox())!;
    expect(Math.round(thumb.width)).toBe(76);
    expect(Math.round(thumb.height)).toBe(76);
    expect(
      await page.locator('#article-list').evaluate((el) => getComputedStyle(el).rowGap),
    ).toBe('34px');

    // Rendered at every width and hidden by CSS at this one -- the card does
    // not read the viewport in JavaScript to decide what to build.
    await expect(page.locator('#card-1 .action-open')).toHaveCount(1);
    await expect(page.locator('#card-1 .action-open')).toBeHidden();
    await expect(page.locator('#card-1 .meta-tag')).toHaveCount(1);
    await expect(page.locator('#card-1 .meta-tag')).toBeHidden();

    // And the Search button is still the way to the field here.
    await expect(page.locator('.search-toggle')).toBeVisible();
  });
});

/**
 * The drawer.
 *
 * Five all-caps labelled sections -- FEEDS / SAVED / SETTINGS / YOU / ADMIN --
 * collapse to three unlabelled groups, a settings block and a footer. The
 * headers go entirely: a drawer with six words in it does not need five more
 * telling you what they are.
 *
 * The same element is the phone's slide-in drawer and the desktop's permanent
 * column, so every claim here is asserted on whichever project it belongs to
 * rather than on a forced viewport.
 */
test.describe('drawer', () => {
  test('has no all-caps section headers', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    await expect(page.locator('.sidebar-section-title')).toHaveCount(0);
  });

  test('is three groups, a settings block and a footer', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    // Three, not "at least three": the failure this guards against is a fourth
    // group added beside the old sections instead of replacing them.
    await expect(page.locator('.drawer-group')).toHaveCount(3);
    // Task 9 replaces the controls inside this container, not the container.
    await expect(page.locator('.drawer-settings')).toHaveCount(1);
    await expect(page.locator('.drawer-footer')).toHaveCount(1);
  });

  test('names the reader and their unread count under the wordmark', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    await expect(page.locator('.drawer-head')).toContainText('Better News');
    // fixtures' ME is "reader" and FEEDS carries 139 unread.
    await expect(page.locator('.drawer-sub')).toContainText('reader');
    await expect(page.locator('.drawer-sub')).toContainText('139 unread');
  });

  test('keeps every group in its own place', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    const groups = page.locator('.drawer-group');
    // 1: the feeds. 2: what a reader keeps and what was kept from them.
    await expect(groups.nth(0)).toContainText('All feeds');
    await expect(groups.nth(1)).toContainText('Saved articles');
    await expect(groups.nth(1)).toContainText('Hidden');
    await expect(groups.nth(1)).toContainText('Your stats');
    // 3: the display preferences, all four of them.
    const settings = page.locator('.drawer-settings');
    await expect(settings.getByRole('switch', { name: 'Show photos' })).toBeVisible();
    await expect(settings.getByRole('switch', { name: 'Compact list' })).toBeVisible();
    await expect(settings.getByRole('radiogroup', { name: 'Sort' })).toBeVisible();
    await expect(settings.getByRole('radiogroup', { name: 'Theme' })).toBeVisible();
  });

  test('feed children sit behind an indent rule', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    const kids = page.locator('.drawer-children');
    const rule = await kids.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { width: cs.borderLeftWidth, pad: cs.paddingLeft };
    });
    expect(rule.width).toBe('2px');
    // 16px on a phone, 14px once the column is permanent.
    expect(['16px', '14px']).toContain(rule.pad);
  });

  test('the footer holds the admin controls, and withholds them from a reader', async ({
    page,
  }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    const footer = page.locator('.drawer-footer');
    // fixtures' ME is an admin, so all three admin screens have a home here.
    for (const name of ['Users', 'Server settings', 'Ollama log']) {
      await expect(footer.getByRole('button', { name, exact: true })).toBeVisible();
    }
    await expect(footer.getByRole('button', { name: 'Sign out' })).toBeVisible();

    await page.route('**/api/v1/me', (r) => r.fulfill({
      json: { id: 2, username: 'plain', role: 'user', must_change_password: false,
              declickbait: false, content_filter_mode: 'off' },
    }));
    await page.reload();
    await page.waitForSelector('.article-row');
    await openDrawer(page);
    for (const name of ['Users', 'Server settings', 'Ollama log']) {
      await expect(footer.getByRole('button', { name, exact: true })).toHaveCount(0);
    }
    // Their own account and the way out stay theirs.
    await expect(footer.getByRole('button', { name: 'Sign out' })).toBeVisible();
    await expect(footer.getByRole('button', { name: 'plain' })).toBeVisible();
  });
});

test.describe('the drawer is the desktop sidebar', () => {
  test.skip(({ isMobile }) => isMobile, 'desktop only');

  test('renders as a permanent 262px column, not an off-screen drawer', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await page.waitForSelector('.article-row');
    const sidebar = page.locator('.sidebar');
    const box = (await sidebar.boundingBox())!;
    expect(Math.round(box.width)).toBe(262);
    // On screen, and never translated out of it: the phone's slide-in
    // transform must be reset here or the permanent column renders off-page.
    expect(box.x).toBe(0);
    expect(await sidebar.evaluate((el) => getComputedStyle(el).transform))
      .toBe('none');
    // The footer sits at the bottom of the column, not under the last group.
    const footer = (await page.locator('.drawer-footer').boundingBox())!;
    expect(footer.y).toBeGreaterThan(box.height / 2);
  });
});

/**
 * Task 9: Photos and Compact are switches; Sort and Theme are segmented
 * radiogroups. Photos keeps its pre-existing accessible name ("Show photos",
 * not the visible "Photos") -- see the controller correction on Toggle --
 * so this is a regression guard as much as a new-behaviour test. Sort and
 * Theme are the two that actually change shape here.
 */
test.describe('drawer controls', () => {
  test('Photos is a switch that reports its state', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    const sw = page.getByRole('switch', { name: 'Show photos' });
    const before = await sw.getAttribute('aria-checked');
    await sw.click();
    await expect(sw).toHaveAttribute('aria-checked', before === 'true' ? 'false' : 'true');
  });

  test('Sort offers exactly Score and Date', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    const group = page.getByRole('radiogroup', { name: 'Sort' });
    await expect(group.getByRole('radio')).toHaveText(['Score', 'Date']);
  });

  test('Theme offers Auto, Light and Dark', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    await openDrawer(page);
    const group = page.getByRole('radiogroup', { name: 'Theme' });
    await expect(group.getByRole('radio')).toHaveText(['Auto', 'Light', 'Dark']);
  });
});

/**
 * Task 10: serif wordmark, underline fields, bottom-weighted CTA on mobile.
 * Username is kept -- no email, no magic link, no "Forgot?" -- see the
 * task brief's Global Constraints and controller correction 3.
 */
test.describe('sign in', () => {
  test('asks for a username, not an email, and offers no magic link', async ({ page }) => {
    await signInFlow(page);
    await page.goto('/');
    await expect(page.locator('.field-label').first()).toHaveText('Username');
    await expect(page.getByText(/magic link/i)).toHaveCount(0);
    await expect(page.getByText(/forgot/i)).toHaveCount(0);
  });

  test('the CTA is pinned to the bottom on a phone', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone only -- on a desktop the column is centred instead');
    await signInFlow(page);
    await page.goto('/');
    const cta = await page.locator('.signin-cta').boundingBox();
    const vp = page.viewportSize()!;
    // Bottom-weighted so the iOS keyboard never covers it.
    expect(cta!.y).toBeGreaterThan(vp.height * 0.6);
  });
});

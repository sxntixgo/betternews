import { expect, test } from '@playwright/test';
import { article, mockApi, signedIn } from './fixtures';

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
    await expect(page.locator('#card-1 .topic-chip')).toHaveCount(0);
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

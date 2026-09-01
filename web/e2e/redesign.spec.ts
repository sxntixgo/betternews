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
  test('stories are separated by space, not rules or tints', async ({ page }) => {
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
    expect(styles.gap).toBe('34px');
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
  test('carries the three text actions with Search at full strength', async ({ page }) => {
    await signedIn(page);
    await mockApi(page);
    await page.goto('/');
    const actions = page.locator('.header-actions');
    await expect(actions.getByText('Refresh')).toBeVisible();
    await expect(actions.getByText('Mark all read')).toBeVisible();
    await expect(actions.getByText('Search')).toBeVisible();
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

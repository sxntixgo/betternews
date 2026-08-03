import { expect, test } from '@playwright/test';
import { article, DETAIL, mockApi, signedIn } from './fixtures';

/**
 * The reading features the server-rendered UI has and the SPA did not:
 * search, the hidden view, dismiss-all, the digest, topic filtering, and the
 * refresh button that waits for the pipeline.
 */
test.beforeEach(async ({ page }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
});

test('search narrows the list, and clearing it restores', async ({ page }) => {
  const before = await page.locator('.article-row').count();
  await page.locator('#search').fill('quantum');
  // Debounced, as the HTML one is -- a request per keystroke would hammer FTS.
  await expect(page.locator('.article-row')).toHaveCount(1);

  await page.locator('#search').fill('');
  await expect(page.locator('.article-row')).toHaveCount(before);
});

test('the hidden view asks for hidden articles', async ({ page, isMobile }) => {
  const asked: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/articles?')) asked.push(r.url());
  });
  // On a phone the sidebar is a drawer, so nothing in it is clickable until it
  // is open -- the same reason the drawer had to exist at all.
  if (isMobile) await page.locator('.drawer-toggle').click();
  await page.locator('.sidebar-feed').filter({ hasText: 'Hidden' }).click();
  await expect.poll(() => asked.some((u) => u.includes('hidden=1'))).toBe(true);
});

test('dismiss-all greys the list without emptying it', async ({ page }) => {
  const before = await page.locator('.article-row').count();
  await page.locator('#dismiss-all-btn').click();
  // Dismissed articles stay visible; that is the whole point of the state.
  await expect(page.locator('.article-row')).toHaveCount(before);
  await expect(page.locator('.article-row.dismissed').first()).toBeVisible();
});

test('the digest shows and can be dismissed', async ({ page }) => {
  const panel = page.locator('#digest-panel');
  await expect(panel).toContainText('Argentina');
  await panel.locator('button').first().click();
  await expect(panel).toBeEmpty();
});

test('a topic chip filters to that topic', async ({ page }) => {
  const asked: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/articles?')) asked.push(r.url());
  });
  await page.locator('.topic-chip').first().click();
  await expect.poll(() => asked.some((u) => u.includes('topic='))).toBe(true);
});

test('refresh kicks the pipeline and reloads when it finishes', async ({ page }) => {
  let stamp = '2026-08-01T10:00:00+00:00';
  await page.route('**/api/v1/status', (r) => r.fulfill({
    json: {
      high_score: [], last_poll_at: null, last_pipeline_run_at: stamp,
      feed_count: 2, article_counts: {},
    },
  }));
  let polled = false;
  await page.route('**/api/v1/poll', (r) => {
    polled = true;
    stamp = '2026-08-01T11:00:00+00:00';   // the run finished
    return r.fulfill({ json: { started: true } });
  });

  await page.locator('#poll-btn').click();
  await expect.poll(() => polled).toBe(true);
  // The button reports progress rather than looking inert for two minutes.
  await expect(page.locator('#poll-btn')).toHaveClass(/is-loading/);
});

test('refresh is offered to an admin and withheld from a plain reader', async ({ page }) => {
  // /poll is admin-only on the server; showing the button to everyone would be
  // a control that 403s, which reads as breakage rather than as a permission.
  await expect(page.locator('#poll-btn')).toBeVisible();

  await page.route('**/api/v1/me', (r) =>
    r.fulfill({ json: { id: 2, username: 'plain', role: 'user', declickbait: false, content_filter_mode: 'off' } }));
  await page.reload();
  await page.waitForSelector('.article-row');
  await expect(page.locator('#poll-btn')).toHaveCount(0);
});

test('scrolling to the end never shows the same article twice', async ({ page }) => {
  // `nextOffset` starts at 0, so if the sentinel intersects before page one
  // lands, `loadMore` appends page one to itself -- React logs duplicate keys
  // and the reader sees the same story twice. The `loading` state could not
  // prevent it (batched, so stale in the callback's closure); `inFlight` can.
  // This asserts the invariant, not the race: it is timing-dependent and does
  // not fail reliably with the guard removed.
  let first = true;
  await page.route('**/api/v1/articles?*', async (r) => {
    if (first) {
      first = false;
      await new Promise((res) => setTimeout(res, 400));
    }
    return r.fallback();
  });
  await page.reload();
  await page.waitForSelector('.article-row');

  for (let i = 0; i < 4; i++) {
    await page.mouse.wheel(0, 4000);
    await page.waitForTimeout(200);
  }
  const titles = await page.locator('.article-row .article-title').allInnerTexts();
  expect(new Set(titles).size).toBe(titles.length);
});

test('an empty list says why, and offers the fix', async ({ page }) => {
  // A bare "Nothing to read" is how a misconfigured model went unnoticed three
  // times. The server decides the wording; the client decides where the button
  // goes.
  await page.route('**/api/v1/articles?*', (r) => r.fulfill({
    json: {
      articles: [], next_offset: null,
      diagnosis: {
        kind: 'no_feeds', title: 'No feeds yet',
        detail: 'Add a feed and the reader will start filling up.',
        action: 'Manage feeds', admin_only: true,
      },
    },
  }));
  await page.reload();
  await expect(page.locator('.diagnosis h2')).toHaveText('No feeds yet');
  // Scoped: the sidebar now has its own "Manage feeds" control with the same
  // accessible name, which is correct -- two ways to the same screen.
  await page.locator('.diagnosis').getByRole('button', { name: 'Manage feeds' }).click();
  await expect(page.locator('.manage-feeds')).toBeVisible();
});

test('an admin-only diagnosis withholds the button from a plain reader', async ({ page }) => {
  await page.route('**/api/v1/me', (r) => r.fulfill({
    json: { id: 2, username: 'plain', role: 'user', must_change_password: false,
            declickbait: false, content_filter_mode: 'off' },
  }));
  await page.route('**/api/v1/articles?*', (r) => r.fulfill({
    json: {
      articles: [], next_offset: null,
      diagnosis: {
        kind: 'ollama_unreachable', title: 'Ollama is unreachable',
        detail: 'Connection refused.', action: 'Ollama settings', admin_only: true,
      },
    },
  }));
  await page.reload();
  // They still get told what is wrong -- just not a button that would 403.
  await expect(page.locator('.diagnosis h2')).toHaveText('Ollama is unreachable');
  await expect(page.getByRole('button', { name: 'Ollama settings' })).toHaveCount(0);
});

test.describe('the sidebar', () => {
  // The sidebar is off-screen on a phone until the drawer is opened; these are
  // about grouping, not about the drawer, which mobile.spec covers.
  test.beforeEach(async ({ page, isMobile }) => {
    if (isMobile) {
      await page.locator('.drawer-toggle').click();
      await expect(page.locator('.sidebar')).toHaveClass(/open/);
    }
  });

  test('groups feeds under their tags, with untagged last', async ({ page }) => {
    // The flat list this replaces ignored Feed.tags entirely, so tagging a feed
    // in Manage Feeds was something you could do and never see the effect of.
    const labels = await page.locator('.sidebar-tag-label').allInnerTexts();
    expect(labels.map((l) => l.toLowerCase())).toEqual(['argentina', 'tech', 'untagged']);

    const tech = page.locator('.sidebar-group').filter({ hasText: 'tech' }).first();
    await expect(tech.locator('.sidebar-feed-nested')).toContainText(['The Verge']);
  });

  test('a collapsed group stays collapsed across a reload', async ({ page }) => {
    const group = page.locator('.sidebar-group').filter({ has: page.locator('.sidebar-tag-label', { hasText: 'tech' }) });
    await expect(group.locator('.sidebar-feed-nested')).toHaveCount(1);
    await group.locator('.sidebar-collapse').click();
    await expect(group.locator('.sidebar-feed-nested')).toHaveCount(0);

    // The whole point with six tags is keeping the ones you are not reading
    // shut; re-opening them on every load would be worse than a flat list.
    await page.reload();
    await page.waitForSelector('.article-row');
    const after = page.locator('.sidebar-group').filter({ has: page.locator('.sidebar-tag-label', { hasText: 'tech' }) });
    await expect(after.locator('.sidebar-feed-nested')).toHaveCount(0);
  });

  test('Hidden lists per-feed counts, and a feed there keeps the hidden filter', async ({ page }) => {
    // "Everything is below the threshold" and "one noisy feed is" are different
    // problems and used to look identical.
    const hiddenGroup = page.locator('.sidebar-group').filter({ hasText: 'Hidden' });
    await expect(hiddenGroup.locator('.sidebar-feed-nested')).toHaveCount(2);

    const request = page.waitForRequest((r) => r.url().includes('/articles?') && r.url().includes('hidden=1'));
    await hiddenGroup.locator('.sidebar-feed-nested').first().click();
    expect((await request).url()).toContain('feed=');
  });
});

test('a hidden article says why, as text rather than a tooltip', async ({ page }) => {
  // The hidden list gets reviewed on a phone, where there is no hover.
  await page.route('**/api/v1/articles?*', (r) => r.fulfill({
    json: {
      articles: [article(1, { hidden: true, score: 0.12,
                              score_reason: 'Celebrity gossip, which you consistently skip.' })],
      next_offset: null, diagnosis: null,
    },
  }));
  await page.reload();
  await expect(page.locator('.hidden-reason'))
    .toHaveText('Hidden: Celebrity gossip, which you consistently skip.');
});

test('an embed renders as a card and loads nothing from a third party', async ({ page }) => {
  const external: string[] = [];
  page.on('request', (r) => {
    const host = new URL(r.url()).host;
    if (!host.includes('localhost') && !host.includes('127.0.0.1')) external.push(host);
  });
  await page.route('**/api/v1/articles/*', (r) => (r.request().method() !== 'GET'
    ? r.fallback()
    : r.fulfill({ json: { ...DETAIL, blocks: [
        { aside: null, label: null, blocks: [
          { type: 'embed', platform: 'twitter', url: 'https://twitter.com/x/status/1' }] },
      ] } })));
  await page.reload();
  await page.waitForSelector('.article-row');
  await page.locator('.article-title').first().click();
  await expect(page.locator('.embed-card')).toBeVisible();
  await expect(page.locator('.embed-platform')).toHaveText('X');
  // The whole reason the toggle went: widgets.js was the one thing in the app
  // that ever contacted anyone else.
  expect(external, `contacted: ${external.join(', ')}`).toEqual([]);
});

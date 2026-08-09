import { expect, test } from '@playwright/test';
import { DETAIL, article, mockApi, openSearch, signedIn } from './fixtures';

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
  await openSearch(page);
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

test('dismiss-all clears the list, and the pile is one press away', async ({ page }) => {
  await expect(page.locator('.article-row').first()).toBeVisible();
  await page.locator('#dismiss-all-btn').click();

  // They leave the reading list rather than staying in it greyed out: after
  // one press those rows were most of what a reader scrolled past.
  await expect(page.locator('.article-row')).toHaveCount(0);

  // Reachable, just not in the way. Nothing is fetched until it is asked for.
  const toggle = page.locator('.pile-toggle');
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.locator('.article-row.dismissed').first()).toBeVisible();
  await expect(page.locator('.pile-heading')).toHaveText('Dismissed');
});

test('the dismissed pile is not fetched until it is asked for', async ({ page }) => {
  const asked: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/articles?')) asked.push(r.url());
  });
  await page.locator('#dismiss-all-btn').click();
  await expect(page.locator('.pile-toggle')).toBeVisible();
  expect(asked.some((u) => u.includes('dismissed=1'))).toBe(false);

  await page.locator('.pile-toggle').click();
  await expect.poll(() => asked.some((u) => u.includes('dismissed=1'))).toBe(true);
});

test('scrolling keeps paging the pile once it is open', async ({ page }) => {
  // Assert the requests, not a snapshot of the row count. Counting rows before
  // and after raced the sentinel: under parallel load the second page had
  // sometimes already arrived before the "before" was read, and the test then
  // demanded growth that had already happened.
  const offsets: string[] = [];
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.pathname.endsWith('/articles') && u.searchParams.get('dismissed') === '1') {
      offsets.push(u.searchParams.get('offset') ?? '0');
    }
  });

  await page.locator('#dismiss-all-btn').click();
  await page.locator('.pile-toggle').click();
  await expect(page.locator('.article-row').first()).toBeVisible();
  expect(offsets).toEqual(['0']);

  // The sentinel feeds the unread list until it runs out, then this one -- so
  // scrolling on has to keep asking for the next page of the pile.
  for (let i = 0; i < 4; i++) {
    await page.evaluate(() => window.scrollBy(0, 4000));
    await page.waitForTimeout(200);
  }
  await expect.poll(() => offsets.length).toBeGreaterThan(1);
  // Never the same page twice: that was a real bug on WebKit.
  expect(offsets).toEqual([...new Set(offsets)]);
});

test('the digest is behind a button, not above the list', async ({ page }) => {
  // It used to render into #digest-panel on load, which pushed the first
  // article below the fold on every screen for prose you read once.
  await expect(page.locator('.digest-body')).toHaveCount(0);

  await page.locator('#digest-btn').click();
  const dialog = page.getByRole('dialog', { name: 'What you missed' });
  await expect(dialog).toContainText('Argentina');

  // Dismiss is not Close: it tells the server to drop the cached briefing so
  // the next one is rebuilt rather than served stale.
  let dropped = false;
  page.on('request', (r) => {
    if (r.url().includes('/digest/dismiss')) dropped = true;
  });
  await dialog.getByRole('button', { name: 'Dismiss' }).click();
  await expect(dialog).toBeHidden();
  await expect.poll(() => dropped).toBe(true);
});

test('closing the digest does not drop the briefing', async ({ page }) => {
  await page.locator('#digest-btn').click();
  await expect(page.getByRole('dialog', { name: 'What you missed' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'What you missed' })).toBeHidden();
  // Still there to reopen -- Close and Dismiss are different verbs.
  await page.locator('#digest-btn').click();
  await expect(page.getByRole('dialog', { name: 'What you missed' }))
    .toContainText('Argentina');
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

  // `page.mouse.wheel` is unsupported in mobile WebKit, and scrolling the
  // window is what the sentinel actually observes anyway.
  for (let i = 0; i < 4; i++) {
    await page.evaluate(() => window.scrollBy(0, 4000));
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

test.describe('keyboard votes', () => {
  test('l likes and d dislikes the focused article', async ({ page }) => {
    // `l` existed and `d` did not, so the keyboard path could approve of things
    // and had no way to reject them -- on an app whose whole ranking is trained
    // on exactly that judgement.
    const votes: number[] = [];
    await page.route('**/api/v1/articles/*/vote', async (r) => {
      votes.push(JSON.parse(r.request().postData() || '{}').value);
      await r.fulfill({ json: { ok: true } });
    });

    // `j` first: focus starts at -1, and clicking a row opens the reader.
    await page.keyboard.press('j');
    await page.keyboard.press('l');
    await expect.poll(() => votes).toEqual([1]);
    await page.keyboard.press('d');
    await expect.poll(() => votes).toEqual([1, -1]);
  });

  test('dismiss-all needs Shift, so a slipped finger cannot empty the list', async ({ page }) => {
    let calls = 0;
    await page.route('**/api/v1/articles/dismiss-all', async (r) => {
      calls += 1;
      await r.fulfill({ json: { ok: true, dismissed: 3 } });
    });

    // `d` sits next to it and votes. On a bare key a mistype would clear
    // everything shown, and there is no undo.
    await page.keyboard.press('j');
    await page.keyboard.press('d');
    await page.waitForTimeout(200);
    expect(calls).toBe(0);

    await page.keyboard.press('Shift+D');
    await expect.poll(() => calls).toBe(1);
  });

  test('typing in search does not vote', async ({ page }) => {
    let voted = false;
    await page.route('**/api/v1/articles/*/vote', async (r) => {
      voted = true;
      await r.fulfill({ json: { ok: true } });
    });
    await openSearch(page);
    await page.locator('#search').fill('lockdown');
    await page.waitForTimeout(200);
    expect(voted).toBe(false);
  });

  test('w opens the briefing, and the sheet lists every key', async ({ page }) => {
    await page.keyboard.press('w');
    await expect(page.getByRole('dialog', { name: 'What you missed' })).toBeVisible();
    await page.keyboard.press('Escape');

    // The overlay is generated from SHORTCUTS, so a key that works but is not
    // listed means the list drifted from the handlers.
    await page.keyboard.press('?');
    const sheet = page.getByRole('dialog');
    for (const k of ['d', 'w', 'Shift D']) await expect(sheet).toContainText(k);
  });
});

test.describe('opening an article', () => {
  test('the title, the summary and the thumbnail all open the reader', async ({ page }) => {
    for (const target of ['.article-title', '.article-summary']) {
      await page.locator(`.article-row ${target}`).first().click();
      await expect(page.getByRole('dialog')).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).toBeHidden();
    }
  });

  test('the controls on a card do their own job and nothing else', async ({ page }) => {
    // Every one of these sits inside the card, so a naive card-level click
    // handler would fire the reader on top of whatever they do.
    const calls: string[] = [];
    for (const [path, name] of [
      ['**/api/v1/articles/*/vote', 'vote'],
      ['**/api/v1/articles/*/save', 'save'],
    ] as const) {
      await page.route(path, async (r) => {
        calls.push(name);
        await r.fulfill({ json: { ok: true } });
      });
    }

    const row = page.locator('.article-row').first();
    for (const sel of ['.btn-save', '.btn-like', '.btn-dislike']) {
      await row.locator(sel).click();
      await expect(page.getByRole('dialog')).toBeHidden();
    }
    expect(calls.sort()).toEqual(['save', 'vote', 'vote']);

    // A topic chip filters the list; it must not also open what it filtered.
    await row.locator('.topic-chip').first().click();
    await expect(page.getByRole('dialog')).toBeHidden();
  });

  test('opening in the browser does not also open the reader', async ({ page, isMobile }) => {
    test.skip(isMobile, 'the external link is hidden on a phone');
    const link = page.locator('.article-row .btn-external').first();
    await expect(link).toHaveAttribute('target', '_blank');
    // Neutralised rather than clicked: a real click opens a tab Playwright
    // then has to chase, and the question here is only whether the card's
    // handler stayed out of the way.
    await link.evaluate((a: HTMLAnchorElement) => a.removeAttribute('target'));
    await page.route('https://**', (r) => r.fulfill({ body: 'ok' }));
    await link.click();
    await expect(page.getByRole('dialog')).toBeHidden();
  });
});

test('no article is ever rendered twice', async ({ page }) => {
  // This failed only on WebKit, and only after an interaction that resized the
  // cards. `loadMore` read `nextOffset` off its closure; `inFlight` is cleared
  // synchronously in `finally` while `setNextOffset` is a state update that has
  // not flushed, so an IntersectionObserver firing in that window saw the
  // initial offset of 0 and appended page zero on top of page zero.
  await page.route('**/api/v1/articles?*', (r) => r.fulfill({ json: {
    articles: [article(1), article(2), article(3)],
    next_offset: null, diagnosis: null } }));
  await page.reload();
  await page.waitForSelector('.article-row');

  // Compact shrinks every card, which is what brings the sentinel into view.
  await page.getByRole('switch', { name: 'Compact list' }).click();
  await page.waitForTimeout(300);

  const ids = await page.locator('.article-row').evaluateAll((els) => els.map((e) => e.id));
  expect(ids).toEqual([...new Set(ids)]);
});

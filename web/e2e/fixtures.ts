import type { Page } from '@playwright/test';
import type { Article, ArticleDetail, FeedList, Me } from '../../shared/api';

/** Shapes mirror shared/api.ts, so a contract change breaks these too. */
export const ME: Me = {
  id: 1, username: 'reader', role: 'admin',
  declickbait: true, content_filter_mode: 'remove',
};

export const FEEDS: FeedList = {
  feeds: [
    { id: 7, title: 'The Verge', unread: 16, hidden: 4, saved: 0, paused: false, tags: [] },
    { id: 8, title: 'LA NACION', unread: 120, hidden: 9, saved: 1, paused: false, tags: [] },
  ],
  unread: 136, saved: 1, hidden: 13,
};

export function article(id: number, over: Partial<Article> = {}): Article {
  return {
    id,
    url: `https://example.com/${id}`,
    title: `Story number ${id} with a headline long enough to wrap on a phone`,
    original_title: null,
    summary: 'A summary that runs to a couple of lines so the card has real height on a narrow screen.',
    score: 0.8,
    score_reason: 'Matches your interests.',
    topics: ['economy', 'politics'],
    feed_id: 8,
    thumbnail_url: null,
    reading_time: '4',
    published_at: '2026-07-20T10:00:00+00:00',
    duplicate_count: 0,
    state: { read: false, saved: false, dismissed: false, opinion: null },
    ...over,
  };
}

export const DETAIL: ArticleDetail = {
  ...article(1),
  description: 'The standfirst.',
  aside_count: 2,
  blocks: [
    { aside: null, label: null, blocks: [{ type: 'p', text: 'The first paragraph of the body.' }] },
    {
      aside: 'related_links',
      label: 'Related stories',
      blocks: [{ type: 'p', text: 'Older news rail that must fold, not vanish.' }],
    },
    { aside: null, label: null, blocks: [{ type: 'p', text: 'The reporting continues here.' }] },
  ],
};

export const DIGEST = {
  body: '**Argentina** — three stories on the peso.\n**Tech** — one on chips.',
  article_count: 7,
  cached: false,
  articles: [{ id: 1, url: 'https://example.com/1' }],
};

/** 25 articles over two pages, so infinite scroll has something to do. */
export async function mockApi(page: Page) {
  await page.route('**/api/v1/digest', (r) => r.fulfill({ json: DIGEST }));
  await page.route('**/api/v1/digest/dismiss', (r) => r.fulfill({ json: { ok: true } }));
  await page.route('**/api/v1/status', (r) => r.fulfill({
    json: {
      high_score: [], last_poll_at: null, last_pipeline_run_at: '2026-08-01T10:00:00+00:00',
      feed_count: 2, article_counts: { summarized: 25, hidden: 4 },
    },
  }));
  await page.route('**/api/v1/search?*', (r) => {
    const q = new URL(r.request().url()).searchParams.get('q') ?? '';
    // Only the first article matches, so a narrowing assertion means something.
    return r.fulfill({ json: { articles: q ? [article(1)] : [] } });
  });
  // Dismiss-all has to change what the list returns afterwards, or a test can
  // only see the count and not the thing that matters: the rows stay, greyed.
  let allDismissed = false;
  await page.route('**/api/v1/articles/dismiss-all*', (r) => {
    allDismissed = true;
    return r.fulfill({ json: { dismissed: 10 } });
  });
  await page.route('**/api/v1/me', (r) => r.fulfill({ json: ME }));
  await page.route('**/api/v1/feeds', (r) => r.fulfill({ json: FEEDS }));
  await page.route('**/api/v1/articles?*', (r) => {
    const offset = Number(new URL(r.request().url()).searchParams.get('offset') ?? 0);
    const ids = Array.from({ length: 10 }, (_, i) => offset + i + 1).filter((n) => n <= 25);
    r.fulfill({
      json: {
        articles: ids.map((n) => article(n, allDismissed
          ? { state: { read: false, saved: false, dismissed: true, opinion: null } }
          : {})),
        next_offset: offset + 10 <= 25 ? offset + 10 : null,
      },
    });
  });
  await page.route('**/api/v1/articles/*', (r) => {
    if (r.request().method() !== 'GET') return r.fallback();
    return r.fulfill({ json: DETAIL });
  });
  // State changes echo the article back with the change applied.
  await page.route('**/api/v1/articles/*/save', (r) =>
    r.fulfill({ json: article(1, { state: { read: false, saved: true, dismissed: false, opinion: null } }) }));
  await page.route('**/api/v1/articles/*/vote', (r) =>
    r.fulfill({ json: article(1, { state: { read: false, saved: false, dismissed: false, opinion: 'liked' } }) }));
}

/**
 * Skip the sign-in screen.
 *
 * There is no token to seed any more -- auth is an HttpOnly cookie the page
 * cannot see, and the app decides by asking /me. Answering that is what makes
 * it think it is signed in.
 */
export async function signedIn(page: Page) {
  await page.route('**/api/v1/me', (r) => r.fulfill({ json: ME }));
}


/**
 * Start signed out, and let a successful login flip it.
 *
 * The app asks `/me` whether it is signed in, because an HttpOnly cookie is
 * invisible to the page. A test that wants to exercise the form has to answer
 * 401 first and 200 afterwards -- the flag here stands in for the cookie the
 * server would have set.
 */
export async function signInFlow(page: Page, opts: { mustChangePassword?: boolean } = {}) {
  let ok = false;
  await page.route('**/api/v1/me', (r) =>
    ok ? r.fulfill({ json: ME }) : r.fulfill({ status: 401, json: { error: 'Not signed in.', status: 401 } }));
  await page.route('**/api/v1/auth/login', (r) => {
    ok = true;
    return r.fulfill({
      json: {
        id: 1, username: 'reader', role: 'admin',
        must_change_password: opts.mustChangePassword ?? false,
      },
    });
  });
}


/**
 * Answer every API call with one status.
 *
 * Twice now a test has broken because the shell grew a new call the test did
 * not know about: the request reached the real server, 401'd, and signed the
 * reader out -- correct behaviour that looks exactly like a regression. A
 * catch-all means adding an endpoint cannot do that again. `except` keeps
 * whatever the caller has already routed, /me in particular.
 */
export async function mockEverything(
  page: Page,
  status: number,
  body: unknown,
  except: string[] = ['**/api/v1/me'],
) {
  for (const pattern of except) {
    // Registered first so the catch-all below cannot shadow them.
    void pattern;
  }
  await page.route('**/api/v1/**', (r) => {
    if (r.request().url().endsWith('/api/v1/me')) return r.fallback();
    return r.fulfill({ status, json: body as object });
  });
}

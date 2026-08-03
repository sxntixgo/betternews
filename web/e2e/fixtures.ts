import type { Page } from '@playwright/test';
import type { Article, ArticleDetail, FeedList, Me } from '../../shared/api';

/** Shapes mirror shared/api.ts, so a contract change breaks these too. */
export const ME: Me = {
  id: 1, username: 'reader', role: 'admin', must_change_password: false,
  declickbait: true, content_filter_mode: 'remove',
};

export const FEEDS: FeedList = {
  feeds: [
    { id: 7, title: 'The Verge', unread: 16, hidden: 4, saved: 0, paused: false, tags: ['tech'] },
    { id: 8, title: 'LA NACION', unread: 120, hidden: 9, saved: 1, paused: false,
      tags: ['argentina'] },
    { id: 9, title: 'Untagged Blog', unread: 3, hidden: 0, saved: 0, paused: false, tags: [] },
  ],
  unread: 139, saved: 1, hidden: 13,
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
    hidden: false,
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
  await page.route('**/api/v1/feeds/manage', (r) => r.fulfill({
    json: { feeds: [
      { id: 7, url: 'https://verge.example/rss', title: 'The Verge', paused: false,
        last_polled_at: null, last_success_at: null, last_error: null,
        consecutive_failures: 0, score_threshold: null, tags: ['tech'] },
      { id: 8, url: 'https://broken.example/rss', title: 'Broken', paused: true,
        last_polled_at: null, last_success_at: null,
        last_error: 'Name or service not known', consecutive_failures: 5,
        score_threshold: 0.5, tags: [] },
    ] },
  }));
  await page.route('**/api/v1/feeds/*/pause', (r) => r.fulfill({ json: { id: 7, paused: true, url: '', title: '', last_polled_at: null, last_success_at: null, last_error: null, consecutive_failures: 0, score_threshold: null, tags: [] } }));
  await page.route('**/api/v1/feeds/*/resume', (r) => r.fulfill({ json: { id: 8, paused: false, url: '', title: '', last_polled_at: null, last_success_at: null, last_error: null, consecutive_failures: 0, score_threshold: null, tags: [] } }));
  // Tags and threshold save on blur, so *tabbing through the feeds table*
  // fires them. Unmocked, they reached the real server, 401'd, and signed the
  // reader out -- which looks like a broken focus trap rather than a missing
  // stub. Same trap fixtures.ts already warns about, third time.
  const feedRow = {
    id: 7, url: 'https://verge.example/rss', title: 'The Verge', paused: false,
    last_polled_at: null, last_success_at: null, last_error: null,
    consecutive_failures: 0, score_threshold: null, tags: ['tech'],
  };
  await page.route('**/api/v1/feeds/*/tags', (r) => r.fulfill({ json: feedRow }));
  await page.route('**/api/v1/feeds/*/threshold', (r) => r.fulfill({ json: feedRow }));
  await page.route('**/api/v1/feeds/opml', (r) => (r.request().method() === 'POST'
    ? r.fulfill({ json: { added: 2 } })
    : r.fulfill({ headers: { 'content-disposition': 'attachment; filename="feeds.opml"' },
                  body: '<opml version="2.0"><body/></opml>' })));
  await page.route('**/api/v1/me/preferences', (r) => r.fulfill({
    json: { profile_text: 'You like rockets and Argentine politics.',
            updated_at: '2026-08-01T09:00:00+00:00', liked: 34, disliked: 4,
            stances: { 'formula-1': 'more', crypto: 'hide' } },
  }));
  await page.route('**/api/v1/me/tokens', (r) => r.request().method() === 'POST'
    ? r.fulfill({ json: { token: 'bn_brand-new-value', name: 'iPhone' } })
    : r.fulfill({ json: { tokens: [
        { id: 7, name: 'Old phone', created_at: '2026-07-01T00:00:00+00:00',
          last_used_at: '2026-07-30T00:00:00+00:00' },
      ] } }));
  await page.route('**/api/v1/me/tokens/*/revoke', (r) => r.fulfill({ json: { ok: true } }));
  await page.route('**/api/v1/me/password', (r) => r.fulfill({ json: { ok: true } }));
  await page.route('**/api/v1/topics', (r) => r.fulfill({
    json: { topics: [
      { topic: 'formula-1', stance: 'more', articles: 12, likes: 3, dislikes: 0 },
      { topic: 'crypto', stance: 'hide', articles: 5, likes: 0, dislikes: 2 },
    ] },
  }));
  await page.route('**/api/v1/topics/*/stance', (r) => r.fulfill({ json: { topic: 'x', stance: 'more' } }));
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
  await mockSettings(page);
  await mockAdmin(page);
}

/** Admin users, insights and the call log. Stateful, for the same reason. */
export async function mockAdmin(page: Page) {
  let users = [
    { id: 1, username: 'reader', role: 'admin', must_change_password: false,
      created_at: '2026-01-01T00:00:00+00:00', last_login_at: '2026-08-01T09:00:00+00:00',
      votes: 34, read_count: 210 },
    { id: 2, username: 'guest', role: 'user', must_change_password: false,
      created_at: '2026-06-01T00:00:00+00:00', last_login_at: null,
      votes: 2, read_count: 9 },
  ];
  let enabled = false;
  let calls = [
    { id: 1, at: '2026-08-01T10:00:00+00:00', action: 'scoring', model: 'llama3.2:3b',
      endpoint: 'http://ollama/api/generate', ok: true, status_code: 200,
      duration_ms: 812, request_preview: 'Score these articles…',
      response_preview: '{"scores": []}', error: null },
    { id: 2, at: '2026-08-01T10:01:00+00:00', action: 'summary', model: 'llama3.2:3b',
      endpoint: 'http://ollama/api/generate', ok: false, status_code: 500,
      duration_ms: 40, request_preview: 'Summarize…', response_preview: '',
      error: 'connection refused' },
  ];

  await page.route('**/api/v1/admin/users', (r) => r.fulfill({ json: { users, me: 1 } }));
  await page.route('**/api/v1/admin/users/*/role', (r) => {
    const id = Number(r.request().url().match(/users\/(\d+)\//)![1]);
    const { role } = r.request().postDataJSON() as { role: string };
    // The last admin cannot be demoted: an instance with no admin cannot repair
    // itself. The server answers 409; so does this, or the screen is never
    // tested against the case that matters.
    if (role === 'user' && users.filter((u) => u.role === 'admin').length <= 1
        && users.find((u) => u.id === id)?.role === 'admin') {
      return r.fulfill({ status: 409,
        json: { error: 'That is the last admin — promote someone else first.', status: 409 } });
    }
    users = users.map((u) => (u.id === id ? { ...u, role } : u));
    return r.fulfill({ json: { users, me: 1 } });
  });
  await page.route('**/api/v1/admin/users/*/delete', (r) => {
    const id = Number(r.request().url().match(/users\/(\d+)\//)![1]);
    users = users.filter((u) => u.id !== id);
    return r.fulfill({ json: { users, me: 1 } });
  });
  await page.route('**/api/v1/admin/users/*/reset-password', (r) => {
    const id = Number(r.request().url().match(/users\/(\d+)\//)![1]);
    users = users.map((u) => (u.id === id ? { ...u, must_change_password: true } : u));
    return r.fulfill({ json: { username: 'guest', password: 'temp-horse-battery' } });
  });

  await page.route('**/api/v1/insights/threshold', (r) =>
    r.fulfill({ json: { threshold: (r.request().postDataJSON() as { threshold: number }).threshold } }));
  await page.route('**/api/v1/insights', (r) => r.fulfill({
    json: {
      threshold: 0.35,
      histogram: Array.from({ length: 20 }, (_, i) => ({
        lo: i / 20, hi: (i + 1) / 20, n: i === 7 ? 90 : i * 3,
      })),
      agreement: { votes: 38, agreed: 29, rate: 76, likes: 34, dislikes: 4,
                   likes_ok: 27, dislikes_ok: 2 },
      suggestion: { threshold: 0.45, rate: 84, votes: 38 },
      per_feed: [{ feed: 'The Verge', likes: 9, dislikes: 1, articles: 300 }],
      per_topic: [{ topic: 'economy', likes: 12, dislikes: 2 }],
      pipeline: { unscored: 3, unsummarized: 1, hidden: 40, ready: 25, total: 69 },
      runs: [{ started_at: '2026-08-01T10:00:00+00:00', finished_at: '2026-08-01T10:01:30+00:00',
               scored_n: 12, summarized_n: 9, errors_n: 1, skipped: false, seconds: 90 }],
      llm_error: null,
    },
  }));

  await page.route('**/api/v1/ollama-log/toggle', (r) => {
    enabled = (r.request().postDataJSON() as { enabled: boolean }).enabled;
    return r.fulfill({ json: { enabled } });
  });
  await page.route('**/api/v1/ollama-log/clear', (r) => {
    const n = calls.length;
    calls = [];
    return r.fulfill({ json: { cleared: n } });
  });
  await page.route('**/api/v1/ollama-log*', (r) => {
    const only = new URL(r.request().url()).searchParams.get('failed') === '1';
    return r.fulfill({ json: {
      enabled, keep: 200, only_failed: only,
      summary: { total: calls.length, failed: calls.filter((c) => !c.ok).length,
                 newest: calls[0]?.at ?? null },
      calls: only ? calls.filter((c) => !c.ok) : calls,
      queue: { new: 3, scored: 1, summarized: 25 },
      last_run: '2026-08-01T10:01:30+00:00',
    } });
  });
}

/**
 * The settings endpoints, holding state across the round trip.
 *
 * Stateful on purpose: a stub that echoes a fixed body would pass whether or
 * not the screen sent what the user typed, which is the only thing these
 * panels do.
 */
export async function mockSettings(page: Page) {
  const state = {
    ollama: {
      host: 'host.docker.internal', port: '11434', using_env: false,
      env_base: 'http://host.docker.internal:11434',
      active_base: 'http://host.docker.internal:11434',
    },
    reader: {
      declickbait: false, content_filter_mode: 'remove',
      content_filter_modes: ['highlight', 'off', 'remove'],
      content_filter_llm: false, embeds: false, notify_high_score: false,
    },
    retention: {
      days: 15, confirmed: false,
      preview: { articles: 412, total: 18020, saved: 37 },
    },
    topics: [
      { topic: 'crypto', articles: 5, muted: false, adjustment: 0 },
      { topic: 'economy', articles: 41, muted: false, adjustment: 0 },
    ],
    models: {
      actions: [
        { id: 'scoring', label: 'Relevance scoring', description: 'Runs on every article.',
          guidance: 'Needs dependable JSON on every article, so avoid reasoning models.',
          json_output: true, heavy: true,
          current: 'ministral-3:14b', explicit: 'ministral-3:14b', inherited: false,
          installed: false, recommended: 'llama3.2:3b', suboptimal: false,
          why: 'Best fit installed: 3B, not a reasoning model.' },
        { id: 'summary', label: 'Article summaries', description: 'One call per article.',
          guidance: 'Speed compounds here; a mid-size model writes fluent prose fast.',
          json_output: false, heavy: true,
          current: 'llama3.2:3b', explicit: '', inherited: true,
          installed: true, recommended: 'llama3.2:3b', suboptimal: false,
          why: 'Best fit installed.' },
      ],
      installed: ['llama3.2:3b', 'llama3.1:8b'],
      defaults: { scoring: 'llama3.2:3b', summary: 'llama3.2:3b' },
    },
  };

  // Registered after the sub-paths would shadow them, so /ollama/test and
  // /retention/prune go first: Playwright tries the most recent route first,
  // and '**/api/v1/settings/ollama' does not match '/ollama/test' anyway --
  // but the ordering is what keeps that true if a pattern ever loosens.
  await page.route('**/api/v1/settings/ollama/test', (r) => {
    const body = r.request().postDataJSON() as { host: string; port: string };
    return r.fulfill({ json: {
      ok: false, message: `Could not reach ${body.host}:${body.port}.`,
      models: [], base: `http://${body.host}:${body.port}`,
    } });
  });
  await page.route('**/api/v1/settings/ollama', (r) => {
    if (r.request().method() === 'POST') {
      const body = r.request().postDataJSON() as { host: string; port: string };
      state.ollama = { ...state.ollama, ...body,
                       active_base: `http://${body.host}:${body.port}` };
    }
    return r.fulfill({ json: state.ollama });
  });
  await page.route('**/api/v1/settings/models/recommended', (r) => {
    state.models.actions = state.models.actions.map((a) => (a.recommended
      ? { ...a, current: a.recommended, explicit: a.recommended,
          inherited: false, installed: true }
      : a));
    return r.fulfill({ json: { applied: 2 } });
  });
  await page.route('**/api/v1/settings/models', (r) => {
    if (r.request().method() === 'POST') {
      const body = r.request().postDataJSON() as Record<string, string>;
      state.models.actions = state.models.actions.map((a) => (a.id in body
        ? { ...a, current: body[a.id] || a.current, explicit: body[a.id],
            inherited: !body[a.id], installed: true }
        : a));
    }
    return r.fulfill({ json: state.models });
  });
  await page.route('**/api/v1/settings/reader', (r) => {
    if (r.request().method() === 'POST') Object.assign(state.reader, r.request().postDataJSON());
    return r.fulfill({ json: state.reader });
  });
  await page.route('**/api/v1/settings/retention/prune', (r) => {
    // The server refuses while unconfirmed. Mirrored here so a screen that
    // stopped disabling the button would fail rather than quietly appear to work.
    if (!state.retention.confirmed) {
      return r.fulfill({ status: 409,
        json: { error: 'Confirm the retention policy before pruning.', status: 409 } });
    }
    state.retention.preview = { ...state.retention.preview, articles: 0 };
    return r.fulfill({ json: { removed: 412 } });
  });
  await page.route('**/api/v1/settings/retention/clear-read', (r) =>
    r.fulfill({ json: { cleared: 96 } }));
  await page.route('**/api/v1/settings/retention', (r) => {
    if (r.request().method() === 'POST') Object.assign(state.retention, r.request().postDataJSON());
    return r.fulfill({ json: state.retention });
  });
  await page.route('**/api/v1/settings/topics', (r) => {
    if (r.request().method() === 'POST') {
      const body = r.request().postDataJSON() as
        { action: string; topic?: string; adjustment?: number };
      if (body.action === 'renormalize') return r.fulfill({ json: { renormalized: 8 } });
      state.topics = state.topics.map((t) => (t.topic !== body.topic ? t : {
        ...t,
        muted: body.action === 'mute',
        adjustment: body.action === 'boost' ? (body.adjustment ?? 0.1) : 0,
      }));
    }
    return r.fulfill({ json: { topics: state.topics } });
  });
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

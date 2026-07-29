/**
 * The Better News API, typed once.
 *
 * Both clients import this: the web SPA and the native app. They speak to the
 * same `/api/v1`, so the request shapes, the response types and the auth header
 * belong in one file rather than being written twice and drifting the first
 * time an endpoint changes.
 *
 * Deliberately dependency-free and built on `fetch`, which browsers and React
 * Native both provide. Nothing here may import from a DOM or a React Native
 * module, or it stops being shareable.
 */

// ── wire types ────────────────────────────────────────────────────────────────

/** What a person has done with an article. Per user, never shared. */
export type Opinion = 'liked' | 'disliked';

export interface ArticleState {
  read: boolean;
  saved: boolean;
  dismissed: boolean;
  opinion: Opinion | null;
}

export interface Article {
  id: number;
  url: string;
  /** Already resolved: the de-clickbaited headline when that setting is on. */
  title: string;
  /** Only set when de-clickbait actually rewrote it — show "Originally: …" then. */
  original_title: string | null;
  summary: string | null;
  score: number | null;
  score_reason: string | null;
  topics: string[];
  feed_id: number | null;
  thumbnail_url: string | null;
  reading_time: string | null;
  published_at: string | null;
  /** How many other feeds carried the same story. */
  duplicate_count: number;
  state: ArticleState;
}

/** A body block, already classified. `aside` marks older-news padding. */
export type Block =
  | { type: 'p'; text: string; aside?: string }
  | { type: 'ul'; items: string[]; aside?: string }
  | { type: 'embed'; platform: string; url: string; aside?: string };

/** Consecutive blocks of the same kind, grouped so a rail folds as one unit. */
export interface BlockGroup {
  aside: string | null;
  label: string | null;
  blocks: Block[];
}

export interface ArticleDetail extends Article {
  description: string;
  blocks: BlockGroup[];
  aside_count: number;
}

export interface ArticlePage {
  articles: Article[];
  /** null at the end of the list. Exact — collapsing happens in SQL. */
  next_offset: number | null;
}

export interface Feed {
  id: number;
  title: string;
  unread: number;
  hidden: number;
  saved: number;
  paused: boolean;
  tags: string[];
}

export interface FeedList {
  feeds: Feed[];
  unread: number;
  saved: number;
  hidden: number;
}

export interface Topic {
  topic: string;
  stance: string | null;
  articles: number;
  likes: number;
  dislikes: number;
}

export interface Me {
  id: number;
  username: string;
  role: 'admin' | 'user';
  declickbait: boolean;
  content_filter_mode: string;
}

export interface Digest {
  body: string | null;
  article_count: number;
  cached: boolean;
  articles: { id: number; url: string }[];
}

export interface ListQuery {
  feed?: number;
  topic?: string;
  hidden?: boolean;
  saved?: boolean;
  sort?: 'date' | 'score';
  limit?: number;
  offset?: number;
}

/** A non-2xx response. The API always sends JSON, including for errors. */
export class ApiError extends Error {
  readonly status: number;

  // Plain fields, not parameter properties: those need TypeScript-specific
  // emit, and this file is compiled by whatever toolchain each client brings.
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
  /** The caller should send the reader back to sign in. */
  get isAuthFailure() {
    return this.status === 401;
  }
}

// ── client ────────────────────────────────────────────────────────────────────

export interface ClientOptions {
  baseUrl: string;
  /**
   * Abandon a request after this long. `fetch` has no timeout of its own, so
   * without one a server that is up but wedged hangs the client forever -- on a
   * phone that means force-quit. 0 disables it.
   */
  timeoutMs?: number;
  /** Read lazily so a client survives the token changing under it. */
  getToken: () => string | null | Promise<string | null>;
  /** Called on 401 so the app can clear the stored token and show sign-in. */
  onAuthFailure?: () => void;
  fetchImpl?: typeof fetch;
}

export class BetterNewsClient {
  private readonly opts: ClientOptions;

  constructor(opts: ClientOptions) {
    this.opts = opts;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const token = await this.opts.getToken();
    const doFetch = this.opts.fetchImpl ?? fetch;

    // Callers pass their own signal to cancel on unmount; the timeout gets its
    // own controller and the two are combined when both are present.
    const timeoutMs = this.opts.timeoutMs ?? 0;
    const timer = timeoutMs > 0 ? new AbortController() : null;
    const handle = timer ? setTimeout(() => timer.abort(), timeoutMs) : null;
    const signal = combineSignals(init.signal ?? null, timer?.signal ?? null);

    let res: Response;
    try {
      res = await doFetch(`${this.opts.baseUrl}/api/v1${path}`, {
      ...init,
      signal,
      headers: {
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.headers ?? {}),
      },
      });
    } finally {
      if (handle !== null) clearTimeout(handle);
    }

    if (res.status === 401) this.opts.onAuthFailure?.();

    if (!res.ok) {
      // The API promises JSON at every status, but a proxy in front of it may
      // not, so falling back keeps the error message useful either way.
      let message = `HTTP ${res.status}`;
      try {
        message = ((await res.json()) as { error?: string }).error ?? message;
      } catch {
        /* non-JSON body: keep the status */
      }
      throw new ApiError(res.status, message);
    }
    return (await res.json()) as T;
  }

  me() {
    return this.request<Me>('/me');
  }

  articles(q: ListQuery = {}, init?: RequestInit) {
    // Built by hand rather than with URLSearchParams: bare React Native ships a
    // polyfill whose `set` throws, so this file would only work on runtimes
    // that happen to replace the global -- and the header above promises that
    // `fetch` is the only requirement.
    const parts: string[] = [];
    const add = (k: string, v: string) =>
      parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
    if (q.feed !== undefined) add('feed', String(q.feed));
    if (q.topic) add('topic', q.topic);
    if (q.hidden) add('hidden', '1');
    if (q.saved) add('saved', '1');
    if (q.sort) add('sort', q.sort);
    if (q.limit !== undefined) add('limit', String(q.limit));
    if (q.offset !== undefined) add('offset', String(q.offset));
    const qs = parts.join('&');
    return this.request<ArticlePage>(`/articles${qs ? `?${qs}` : ''}`, init);
  }

  /**
   * Fetching an article marks it read, exactly as opening the web reader does,
   * and the returned `state.read` already reflects that.
   */
  article(id: number, init?: RequestInit) {
    return this.request<ArticleDetail>(`/articles/${id}`, init);
  }

  /** **Toggles**: saving an already-saved article unsaves it. */
  save(id: number) {
    return this.request<Article>(`/articles/${id}/save`, { method: 'POST' });
  }

  dismiss(id: number) {
    return this.request<Article>(`/articles/${id}/dismiss`, { method: 'POST' });
  }

  markRead(id: number) {
    return this.request<Article>(`/articles/${id}/read`, { method: 'POST' });
  }

  /** **Sets**, and does not toggle: voting the same way twice is idempotent. */
  vote(id: number, value: 1 | -1) {
    return this.request<Article>(`/articles/${id}/vote`, {
      method: 'POST',
      body: JSON.stringify({ value }),
    });
  }

  feeds() {
    return this.request<FeedList>('/feeds');
  }

  topics() {
    return this.request<{ topics: Topic[] }>('/topics');
  }

  setStance(topic: string, stance: 'more' | 'hide' | null) {
    return this.request<{ topic: string; stance: string | null }>(
      `/topics/${encodeURIComponent(topic)}/stance`,
      { method: 'POST', body: JSON.stringify({ stance }) },
    );
  }

  digest() {
    return this.request<Digest>('/digest');
  }
}


/** One signal from up to two, without assuming `AbortSignal.any` exists. */
function combineSignals(
  a: AbortSignal | null,
  b: AbortSignal | null,
): AbortSignal | undefined {
  if (!a) return b ?? undefined;
  if (!b) return a;
  const ctrl = new AbortController();
  const stop = () => ctrl.abort();
  for (const s of [a, b]) {
    if (s.aborted) {
      ctrl.abort();
      break;
    }
    s.addEventListener('abort', stop, { once: true });
  }
  return ctrl.signal;
}

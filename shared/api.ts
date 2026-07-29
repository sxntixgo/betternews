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
export interface ArticleState {
  read: boolean;
  saved: boolean;
  dismissed: boolean;
  /** "liked" | "disliked" | null */
  opinion: string | null;
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
    const res = await doFetch(`${this.opts.baseUrl}/api/v1${path}`, {
      ...init,
      headers: {
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.headers ?? {}),
      },
    });

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

  articles(q: ListQuery = {}) {
    const p = new URLSearchParams();
    if (q.feed !== undefined) p.set('feed', String(q.feed));
    if (q.topic) p.set('topic', q.topic);
    if (q.hidden) p.set('hidden', '1');
    if (q.saved) p.set('saved', '1');
    if (q.sort) p.set('sort', q.sort);
    if (q.limit !== undefined) p.set('limit', String(q.limit));
    if (q.offset !== undefined) p.set('offset', String(q.offset));
    const qs = p.toString();
    return this.request<ArticlePage>(`/articles${qs ? `?${qs}` : ''}`);
  }

  /** Fetching an article marks it read, exactly as opening the web reader does. */
  article(id: number) {
    return this.request<ArticleDetail>(`/articles/${id}`);
  }

  save(id: number) {
    return this.request<Article>(`/articles/${id}/save`, { method: 'POST' });
  }

  dismiss(id: number) {
    return this.request<Article>(`/articles/${id}/dismiss`, { method: 'POST' });
  }

  markRead(id: number) {
    return this.request<Article>(`/articles/${id}/read`, { method: 'POST' });
  }

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

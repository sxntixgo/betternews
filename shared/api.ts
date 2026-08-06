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
  /** Scored below the threshold. `score_reason` then says why, and is worth
   *  showing as text rather than hiding in a tooltip. */
  hidden: boolean;
  topics: string[];
  /** What *kind* of story: fixture, transfer, analysis… See app/kinds.py.
   *  Null on articles scored before kinds existed. */
  kind: string | null;
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

/**
 * Why the reading list is empty.
 *
 * Only ever set for an empty first page. A bare "Nothing to read" is how a
 * misconfigured model went unnoticed three times -- the server can tell "no
 * feeds" from "Ollama unreachable" from "still working" from "caught up", and
 * a client cannot.
 *
 * Branch on `kind`, not on the wording. `action` is a label only: the server
 * used to name an href with it, and a client owns its own navigation.
 */
export interface Diagnosis {
  kind:
    | 'no_feeds' | 'not_polled' | 'ollama_unreachable' | 'model_missing'
    | 'llm_failing' | 'processing' | 'all_hidden' | 'caught_up';
  title: string;
  detail: string;
  action: string | null;
  /** Nothing a plain reader can act on; say less rather than send them nowhere. */
  admin_only: boolean;
}

export interface ArticlePage {
  articles: Article[];
  /** null at the end of the list. Exact — collapsing happens in SQL. */
  next_offset: number | null;
  /** Set only when the first page comes back empty. */
  diagnosis: Diagnosis | null;
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

/** What a successful password login returns. Deliberately not a credential. */
export interface LoginResult {
  id: number;
  username: string;
  role: 'admin' | 'user';
  /** An admin reset this password; the reader should be asked to change it. */
  must_change_password: boolean;
}

export interface Me {
  id: number;
  username: string;
  role: 'admin' | 'user';
  /** An admin reset this password. Nothing else is reachable until it changes. */
  must_change_password: boolean;
  declickbait: boolean;
  content_filter_mode: string;
}

/** What the reading client polls to know when new articles have landed. */
export interface Status {
  /** Returned once per reader per article; the server tracks that. */
  high_score: { id: number; title: string; score: number | null }[];
  last_poll_at: string | null;
  /** Refetch the list when this advances. */
  last_pipeline_run_at: string | null;
  feed_count: number;
  article_counts: Record<string, number>;
}

/** A device that can reach the API. Never carries the token itself. */
export interface TokenSummary {
  id: number;
  name: string;
  created_at: string | null;
  last_used_at: string | null;
}

/** The interest profile, with the evidence that produced it. */
export interface Preferences {
  profile_text: string;
  updated_at: string | null;
  liked: number;
  disliked: number;
  /** topic -> "more" | "hide" */
  stances: Record<string, string>;
}

/** A feed as the management screen needs it, health included. */
export interface ManagedFeed {
  id: number;
  url: string;
  title: string | null;
  paused: boolean;
  last_polled_at: string | null;
  last_success_at: string | null;
  /** Why the last poll failed. A silent outage is what this exists to prevent. */
  last_error: string | null;
  consecutive_failures: number;
  /** null means "use the global threshold". */
  score_threshold: number | null;
  tags: string[];
}

export interface Digest {
  body: string | null;
  article_count: number;
  cached: boolean;
  articles: { id: number; url: string }[];
}

/**
 * The Ollama endpoint, and which one is actually in force.
 *
 * `using_env` is worth sending rather than letting a client infer it from two
 * empty strings: blank means "fall back to the environment", and showing empty
 * boxes with no explanation is how a working setup looks broken.
 */
export interface OllamaSettings {
  host: string;
  port: string;
  using_env: boolean;
  env_base: string;
  active_base: string;
}

export interface OllamaProbe {
  ok: boolean;
  message: string;
  models: string[];
  base: string;
}

/** One Ollama job, its model, and everything that explains the recommendation. */
export interface ModelAction {
  id: string;
  label: string;
  description: string;
  /** Why this job wants what it wants. The text that stops someone choosing a
   *  model which fails silently on every call. */
  guidance: string;
  /** Needs structured output, so a reasoning model is fatal rather than slow. */
  json_output: boolean;
  /** Runs per article, so speed compounds. */
  heavy: boolean;
  current: string;
  /** Blank when the job is falling back rather than configured. `current`
   *  alone cannot distinguish "set to llama3.2:3b" from "defaulting to it". */
  explicit: string;
  inherited: boolean;
  /** null when Ollama is unreachable — unknown, which is not the same as false. */
  installed: boolean | null;
  recommended: string | null;
  why: string;
  /** The current choice is actively a poor one, not merely not-the-suggestion. */
  suboptimal: boolean;
}

export interface ModelSettings {
  actions: ModelAction[];
  installed: string[];
  defaults: { scoring: string; summary: string };
}

export interface ReaderSettings {
  declickbait: boolean;
  content_filter_mode: string;
  content_filter_modes: string[];
  content_filter_llm: boolean;
  notify_high_score: boolean;
}

export interface RetentionSettings {
  days: number;
  /** Ships false. Nothing is pruned until someone confirms. */
  confirmed: boolean;
  preview: { articles: number; total: number; saved: number };
}

/** An admin topic rule: applies to every reader, unlike a per-user stance. */
export interface TopicRule {
  topic: string;
  articles: number;
  muted: boolean;
  adjustment: number;
}

/** A user as the admin table needs them, activity included. */
export interface AdminUser {
  id: number;
  username: string;
  role: string;
  must_change_password: boolean;
  created_at: string | null;
  last_login_at: string | null;
  votes: number;
  read_count: number;
}

export interface AdminUserList {
  users: AdminUser[];
  /** Your own id. The client must not offer Delete on your own row. */
  me: number;
}

/** One bucket of the score histogram. All 20 are always sent, empties included. */
export interface HistogramBucket {
  lo: number;
  hi: number;
  n: number;
}

/** How often the score agreed with the vote. */
export interface Agreement {
  votes: number;
  agreed: number;
  /** null when nothing has been voted on. A rate over no votes is not 0%. */
  rate: number | null;
  likes: number;
  dislikes: number;
  likes_ok: number;
  dislikes_ok: number;
}

export interface FeedAccuracy {
  feed: string;
  likes: number;
  dislikes: number;
  articles: number;
}

export interface TopicAccuracy {
  topic: string;
  likes: number;
  dislikes: number;
}

export interface PipelineRun {
  started_at: string | null;
  finished_at: string | null;
  scored_n: number;
  summarized_n: number;
  errors_n: number;
  skipped: boolean;
  seconds: number | null;
}

export interface Insights {
  threshold: number;
  histogram: HistogramBucket[];
  agreement: Agreement;
  /** null with no votes: a suggestion from no data is a number with no meaning. */
  suggestion: { threshold: number; rate: number; votes: number } | null;
  per_feed: FeedAccuracy[];
  per_topic: TopicAccuracy[];
  pipeline: { unscored: number; unsummarized: number; hidden: number; ready: number; total: number };
  runs: PipelineRun[];
  /** Why the last run failed. A 0-scored run in ~0s is broken, not idle. */
  llm_error: string | null;
}

/** One Ollama request and what came back. */
export interface OllamaCall {
  id: number;
  at: string | null;
  action: string | null;
  model: string | null;
  endpoint: string | null;
  ok: boolean;
  status_code: number | null;
  duration_ms: number | null;
  request_preview: string | null;
  response_preview: string | null;
  error: string | null;
}

export interface OllamaLog {
  enabled: boolean;
  keep: number;
  only_failed: boolean;
  summary: { total: number; failed: number; newest: string | null };
  calls: OllamaCall[];
  /** An empty log means no calls are being made, or none are needed. This says which. */
  queue: Record<string, number>;
  last_run: string | null;
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
   * Bearer token, for clients that cannot hold a cookie -- the native app.
   *
   * Optional: a browser signs in with `login()` and is authenticated by an
   * HttpOnly session cookie it never sees. Omit this there, and nothing
   * credential-shaped is ever in reach of JavaScript.
   */
  getToken?: () => string | null | Promise<string | null>;
  /**
   * Abandon a request after this long. `fetch` has no timeout of its own, so
   * without one a server that is up but wedged hangs the client forever -- on a
   * phone that means force-quit. 0 disables it.
   */
  timeoutMs?: number;
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
    const token = this.opts.getToken ? await this.opts.getToken() : null;
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
        // Only JSON string bodies: a FormData upload must keep the
        // browser-set multipart boundary.
        ...(typeof init.body === 'string' ? { 'Content-Type': 'application/json' } : {}),
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

  /**
   * Fetch a file body, with the same auth and error handling as everything
   * else. The filename comes from Content-Disposition when the server sends
   * one, because the URL does not carry it.
   */
  private async download(path: string, fallbackName: string) {
    const token = this.opts.getToken ? await this.opts.getToken() : null;
    const doFetch = this.opts.fetchImpl ?? fetch;
    const res = await doFetch(`${this.opts.baseUrl}/api/v1${path}`, {
      credentials: 'include',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (res.status === 401) this.opts.onAuthFailure?.();
    if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
    const disposition = res.headers.get('Content-Disposition') ?? '';
    const match = /filename="([^"]+)"/.exec(disposition);
    return { blob: await res.blob(), filename: match?.[1] ?? fallbackName };
  }

  /**
   * Sign in with a password. The server replies with a session cookie; there is
   * no token here and nothing for the caller to store.
   */
  login(username: string, password: string) {
    return this.request<LoginResult>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  }

  logout() {
    return this.request<{ ok: boolean }>('/auth/logout', { method: 'POST' });
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

  dismissDigest() {
    return this.request<{ ok: boolean }>('/digest/dismiss', { method: 'POST' });
  }

  search(q: string, init?: RequestInit) {
    return this.request<{ articles: Article[] }>(
      `/search?q=${encodeURIComponent(q)}`, init);
  }

  /** Dismisses the list the caller is looking at, so pass the same filters. */
  dismissAll(q: ListQuery = {}) {
    const parts: string[] = [];
    if (q.feed !== undefined) parts.push(`feed=${encodeURIComponent(String(q.feed))}`);
    if (q.topic) parts.push(`topic=${encodeURIComponent(q.topic)}`);
    if (q.hidden) parts.push('hidden=1');
    if (q.saved) parts.push('saved=1');
    const qs = parts.join('&');
    return this.request<{ dismissed: number }>(
      `/articles/dismiss-all${qs ? `?${qs}` : ''}`, { method: 'POST' });
  }

  status() {
    return this.request<Status>('/status');
  }

  manageFeeds() {
    return this.request<{ feeds: ManagedFeed[] }>('/feeds/manage');
  }

  addFeed(url: string) {
    return this.request<ManagedFeed>('/feeds', {
      method: 'POST', body: JSON.stringify({ url }),
    });
  }

  deleteFeed(id: number) {
    return this.request<{ deleted: number }>(`/feeds/${id}`, { method: 'DELETE' });
  }

  pauseFeed(id: number) {
    return this.request<ManagedFeed>(`/feeds/${id}/pause`, { method: 'POST' });
  }

  resumeFeed(id: number) {
    return this.request<ManagedFeed>(`/feeds/${id}/resume`, { method: 'POST' });
  }

  /** null clears it, falling back to the global threshold. */
  setFeedThreshold(id: number, threshold: number | null) {
    return this.request<ManagedFeed>(`/feeds/${id}/threshold`, {
      method: 'POST', body: JSON.stringify({ threshold }),
    });
  }

  setFeedTags(id: number, tags: string | string[]) {
    return this.request<ManagedFeed>(`/feeds/${id}/tags`, {
      method: 'POST', body: JSON.stringify({ tags }),
    });
  }

  /** Returns the bytes, not a URL: a download cannot carry the auth header. */
  async exportOpml(): Promise<{ blob: Blob; filename: string }> {
    return this.download('/feeds/opml', 'feeds.opml');
  }

  /** Markdown export, same reasoning. */
  async exportMarkdown(scope: 'saved' | 'liked' | 'all' = 'saved') {
    return this.download(`/export?scope=${scope}`, `betternews-${scope}.zip`);
  }

  async importOpml(file: File) {
    const form = new FormData();
    form.append('file', file);
    // No Content-Type: the browser must set the multipart boundary itself.
    return this.request<{ added: number }>('/feeds/opml', { method: 'POST', body: form });
  }

  register(username: string, password: string) {
    return this.request<LoginResult>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  }

  changePassword(current: string, next: string, confirm: string) {
    return this.request<{ ok: boolean }>('/me/password', {
      method: 'POST',
      body: JSON.stringify({ current, new: next, confirm }),
    });
  }

  tokens() {
    return this.request<{ tokens: TokenSummary[] }>('/me/tokens');
  }

  /** The only call that ever returns a token value. */
  createToken(name: string) {
    return this.request<{ token: string; name: string }>('/me/tokens', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  revokeToken(id: number) {
    return this.request<{ ok: boolean }>(`/me/tokens/${id}/revoke`, { method: 'POST' });
  }

  preferences() {
    return this.request<Preferences>('/me/preferences');
  }

  savePreferences(profileText: string) {
    return this.request<{ profile_text: string }>('/me/preferences', {
      method: 'POST',
      body: JSON.stringify({ profile_text: profileText }),
    });
  }

  regeneratePreferences() {
    return this.request<{ started: boolean }>('/me/preferences/regenerate', {
      method: 'POST',
    });
  }

  /** Admin only. Kicks feed polling and the pipeline; returns immediately. */
  poll() {
    return this.request<{ started: boolean }>('/poll', { method: 'POST' });
  }

  /** Admin only. Requeues hidden articles and returns how many. */
  rescoreHidden() {
    return this.request<{ requeued: number }>('/rescore-hidden', { method: 'POST' });
  }

  // ── settings, all admin only ───────────────────────────────────────────────

  ollamaSettings() {
    return this.request<OllamaSettings>('/settings/ollama');
  }

  saveOllama(host: string, port: string) {
    return this.request<OllamaSettings>('/settings/ollama', {
      method: 'POST', body: JSON.stringify({ host, port }),
    });
  }

  /**
   * Probes a host/port without storing it.
   *
   * Deliberately takes the values rather than reading the saved ones: saving
   * first and testing after is how a working configuration gets replaced by a
   * broken one.
   */
  testOllama(host: string, port: string) {
    return this.request<OllamaProbe>('/settings/ollama/test', {
      method: 'POST', body: JSON.stringify({ host, port }),
    });
  }

  modelSettings() {
    return this.request<ModelSettings>('/settings/models');
  }

  /** A partial map of job id → model. Unknown ids are refused, not ignored. */
  saveModels(models: Record<string, string>) {
    return this.request<ModelSettings>('/settings/models', {
      method: 'POST', body: JSON.stringify(models),
    });
  }

  useRecommendedModels() {
    return this.request<{ applied: number }>('/settings/models/recommended', {
      method: 'POST',
    });
  }

  readerSettings() {
    return this.request<ReaderSettings>('/settings/reader');
  }

  /** Only the keys present are written, so a panel can send one toggle. */
  saveReaderSettings(patch: Partial<ReaderSettings>) {
    return this.request<ReaderSettings>('/settings/reader', {
      method: 'POST', body: JSON.stringify(patch),
    });
  }

  retentionSettings() {
    return this.request<RetentionSettings>('/settings/retention');
  }

  saveRetention(patch: { days?: number; confirmed?: boolean }) {
    return this.request<RetentionSettings>('/settings/retention', {
      method: 'POST', body: JSON.stringify(patch),
    });
  }

  /** Throws a 409 until the policy is confirmed. This one deletes articles. */
  pruneNow() {
    return this.request<{ removed: number }>('/settings/retention/prune', {
      method: 'POST',
    });
  }

  clearRead(userIds?: number[]) {
    const body = userIds ? { user_ids: userIds } : { all_users: true };
    return this.request<{ cleared: number }>('/settings/retention/clear-read', {
      method: 'POST', body: JSON.stringify(body),
    });
  }

  topicRules() {
    return this.request<{ topics: TopicRule[] }>('/settings/topics');
  }

  setTopicRule(action: 'mute' | 'boost' | 'clear', topic: string, adjustment?: number) {
    return this.request<{ topics: TopicRule[] }>('/settings/topics', {
      method: 'POST', body: JSON.stringify({ action, topic, adjustment }),
    });
  }

  /** Re-slugs stored topics through the current aliases. */
  tidyTopics() {
    return this.request<{ renormalized: number }>('/settings/topics', {
      method: 'POST', body: JSON.stringify({ action: 'renormalize' }),
    });
  }

  // ── admin and ops, all admin only ──────────────────────────────────────────

  adminUsers() {
    return this.request<AdminUserList>('/admin/users');
  }

  /** 409 on the last admin: an instance with no admin cannot repair itself. */
  setUserRole(id: number, role: 'user' | 'admin') {
    return this.request<AdminUserList>(`/admin/users/${id}/role`, {
      method: 'POST', body: JSON.stringify({ role }),
    });
  }

  deleteUser(id: number) {
    return this.request<AdminUserList>(`/admin/users/${id}/delete`, { method: 'POST' });
  }

  /**
   * Returns the new password once. It is stored nowhere else, so a client that
   * drops it has to reset again.
   */
  resetUserPassword(id: number, password?: string) {
    return this.request<{ username: string; password: string }>(
      `/admin/users/${id}/reset-password`,
      { method: 'POST', body: JSON.stringify({ password }) },
    );
  }

  /** Every insights panel in one call: they are only ever read together. */
  insights() {
    return this.request<Insights>('/insights');
  }

  applyThreshold(threshold: number) {
    return this.request<{ threshold: number }>('/insights/threshold', {
      method: 'POST', body: JSON.stringify({ threshold }),
    });
  }

  ollamaLog(failedOnly = false) {
    return this.request<OllamaLog>(`/ollama-log${failedOnly ? '?failed=1' : ''}`);
  }

  setOllamaLog(enabled: boolean) {
    return this.request<{ enabled: boolean }>('/ollama-log/toggle', {
      method: 'POST', body: JSON.stringify({ enabled }),
    });
  }

  clearOllamaLog() {
    return this.request<{ cleared: number }>('/ollama-log/clear', { method: 'POST' });
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

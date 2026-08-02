import { useCallback, useEffect, useState } from 'react';
import type { Article, FeedList, ListQuery, Me } from '@shared/api';
import { api, setAuthFailureHandler } from './api/client';
import { useArticles } from './api/useArticles';
import { ArticleCard } from './components/ArticleCard';
import { Reader } from './components/Reader';
import { Digest } from './components/Digest';
import { Toolbar } from './components/Toolbar';
import { SignIn } from './screens/SignIn';
import './App.css';

export default function App() {
  // The cookie is HttpOnly, so the page cannot tell whether it is signed in by
  // looking. Ask the server once instead.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  useEffect(() => {
    // Re-runs when signedIn flips, not just on mount: the first call 401s while
    // signed out, and without asking again after login the app never learns who
    // the reader is -- so admin-only controls stay hidden for an admin.
    if (signedIn === false) return;
    api.me().then((u) => { setMe(u); setSignedIn(true); }).catch(() => setSignedIn(false));
  }, [signedIn]);
  const [feeds, setFeeds] = useState<FeedList | null>(null);
  const [feed, setFeed] = useState<number | undefined>();
  const [saved, setSaved] = useState(false);
  const [sort, setSort] = useState<'date' | 'score'>('date');
  const [hidden, setHidden] = useState(false);
  const [topic, setTopic] = useState<string | undefined>();
  const [search, setSearch] = useState('');
  const [me, setMe] = useState<Me | null>(null);
  // Bumped to force the list to refetch after a poll or a dismiss-all.
  const [reloads, setReloads] = useState(0);
  const [reading, setReading] = useState<number | null>(null);
  // At <=720px the carried-over stylesheet parks the sidebar off-screen and
  // waits for `.open`. Carrying CSS across does not carry the JavaScript its
  // rules assume, so without this the sidebar was not merely hidden on a phone
  // -- it was unreachable, and no desktop viewport would ever show that.
  const [drawerOpen, setDrawerOpen] = useState(false);

  // A 401 from anywhere drops straight back to sign-in rather than leaving the
  // reader staring at an empty list.
  useEffect(() => setAuthFailureHandler(() => setSignedIn(false)), []);

  const { articles, loading, error, loadMore, hasMore, patch } = useArticles(
    { feed, saved: saved || undefined, hidden: hidden || undefined, topic,
      sort, limit: 50, reloads } as ListQuery & { reloads: number },
    signedIn === true,
    search,
  );

  useEffect(() => {
    if (signedIn) void api.feeds().then(setFeeds).catch(() => {});
  }, [signedIn, articles.length]);

  // Infinite scroll: load the next page when the sentinel scrolls into view.
  const sentinel = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node || !hasMore) return;
      const io = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) loadMore();
      });
      io.observe(node);
      return () => io.disconnect();
    },
    [hasMore, loadMore],
  );

  if (signedIn === null) return <p className="loading">Loading…</p>;
  if (!signedIn) return <SignIn onDone={() => setSignedIn(true)} />;

  const vote = (a: Article, value: 1 | -1) =>
    api.vote(a.id, value).then(patch).catch(() => {});
  const save = (a: Article) => api.save(a.id).then(patch).catch(() => {});

  // Choosing anything closes the drawer: on a phone the list is behind it.
  const choose = (fn: () => void) => {
    fn();
    setTopic(undefined);
    setSearch('');
    setDrawerOpen(false);
  };

  return (
    <div className="site-layout">
      <button
        className="drawer-toggle"
        aria-label="Feeds"
        aria-expanded={drawerOpen}
        onClick={() => setDrawerOpen((v) => !v)}
      >
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                d="M4 7h16 M4 12h16 M4 17h16" />
        </svg>
      </button>
      <div
        className={`drawer-scrim ${drawerOpen ? 'visible' : ''}`}
        onClick={() => setDrawerOpen(false)}
      />

      <aside className={`sidebar ${drawerOpen ? 'open' : ''}`}>
        <div className="sidebar-brand">Better News</div>
        <button
          className={`sidebar-feed ${feed === undefined && !saved ? 'active' : ''}`}
          onClick={() => choose(() => {
            setFeed(undefined);
            setSaved(false);
            setHidden(false);
          })}
        >
          All feeds
          {feeds && feeds.unread > 0 && <span className="sidebar-feed-count">{feeds.unread}</span>}
        </button>
        {feeds?.feeds.map((f) => (
          <button
            key={f.id}
            className={`sidebar-feed sidebar-feed-nested ${feed === f.id ? 'active' : ''}`}
            onClick={() => choose(() => {
              setFeed(f.id);
              setSaved(false);
              setHidden(false);
            })}
          >
            {f.title}
            {f.unread > 0 && <span className="sidebar-feed-count">{f.unread}</span>}
          </button>
        ))}
        <button
          className={`sidebar-feed ${saved ? 'active' : ''}`}
          onClick={() => choose(() => {
            setSaved(true);
            setFeed(undefined);
            setHidden(false);
          })}
        >
          Saved
          {feeds && feeds.saved > 0 && <span className="sidebar-feed-count">{feeds.saved}</span>}
        </button>
        <button
          className={`sidebar-feed ${hidden ? 'active' : ''}`}
          onClick={() => choose(() => {
            setHidden(true);
            setSaved(false);
            setFeed(undefined);
          })}
        >
          Hidden
          {feeds && feeds.hidden > 0 && <span className="sidebar-feed-count">{feeds.hidden}</span>}
        </button>
      </aside>

      <main className="site-content">
        <header className="site-header">
          <Toolbar
            search={search}
            onSearch={setSearch}
            sort={sort}
            onSort={setSort}
            canPoll={me?.role === 'admin'}
            onRefreshed={() => setReloads((n) => n + 1)}
            onDismissAll={async () => {
              await api.dismissAll({ feed, saved: saved || undefined,
                                     hidden: hidden || undefined, topic });
              setReloads((n) => n + 1);
            }}
          />
        </header>

        <div id="digest-panel">{!search && !topic && <Digest />}</div>

        <div id="article-list">
          {error && <p className="error">{error}</p>}
          {articles.map((a) => (
            <ArticleCard
              key={a.id}
              article={a}
              onOpen={(x) => setReading(x.id)}
              onVote={vote}
              onSave={save}
              onTopic={(t) => { setTopic(t); setSearch(''); }}
            />
          ))}
          {loading && <p className="loading">Loading…</p>}
          {!loading && articles.length === 0 && !error && (
            <p className="empty">Nothing to read.</p>
          )}
          <div ref={sentinel} />
        </div>
      </main>

      {reading !== null && <Reader id={reading} onClose={() => setReading(null)} />}
    </div>
  );
}

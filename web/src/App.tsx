import { useCallback, useEffect, useState } from 'react';
import type { Article, FeedList } from '@shared/api';
import { api, getToken, setAuthFailureHandler } from './api/client';
import { useArticles } from './api/useArticles';
import { ArticleCard } from './components/ArticleCard';
import { Reader } from './components/Reader';
import { SignIn } from './screens/SignIn';
import './App.css';

export default function App() {
  const [signedIn, setSignedIn] = useState(() => getToken() !== null);
  const [feeds, setFeeds] = useState<FeedList | null>(null);
  const [feed, setFeed] = useState<number | undefined>();
  const [saved, setSaved] = useState(false);
  const [sort, setSort] = useState<'date' | 'score'>('date');
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
    { feed, saved: saved || undefined, sort, limit: 50 },
    signedIn,
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

  if (!signedIn) return <SignIn onDone={() => setSignedIn(true)} />;

  const vote = (a: Article, value: 1 | -1) =>
    api.vote(a.id, value).then(patch).catch(() => {});
  const save = (a: Article) => api.save(a.id).then(patch).catch(() => {});

  // Choosing anything closes the drawer: on a phone the list is behind it.
  const choose = (fn: () => void) => {
    fn();
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
          })}
        >
          Saved
          {feeds && feeds.saved > 0 && <span className="sidebar-feed-count">{feeds.saved}</span>}
        </button>
      </aside>

      <main className="site-content">
        <header className="site-header">
          <div className="sort-toggle">
            <button className={sort === 'score' ? 'active' : ''} onClick={() => setSort('score')}>
              Score
            </button>
            <button className={sort === 'date' ? 'active' : ''} onClick={() => setSort('date')}>
              Date
            </button>
          </div>
        </header>

        <div id="article-list">
          {error && <p className="error">{error}</p>}
          {articles.map((a) => (
            <ArticleCard
              key={a.id}
              article={a}
              onOpen={(x) => setReading(x.id)}
              onVote={vote}
              onSave={save}
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

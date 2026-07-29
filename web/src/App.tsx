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

  return (
    <div className="site-layout">
      <aside className="sidebar">
        <div className="sidebar-brand">Better News</div>
        <button
          className={`sidebar-feed ${feed === undefined && !saved ? 'active' : ''}`}
          onClick={() => {
            setFeed(undefined);
            setSaved(false);
          }}
        >
          All feeds
          {feeds && feeds.unread > 0 && <span className="sidebar-feed-count">{feeds.unread}</span>}
        </button>
        {feeds?.feeds.map((f) => (
          <button
            key={f.id}
            className={`sidebar-feed sidebar-feed-nested ${feed === f.id ? 'active' : ''}`}
            onClick={() => {
              setFeed(f.id);
              setSaved(false);
            }}
          >
            {f.title}
            {f.unread > 0 && <span className="sidebar-feed-count">{f.unread}</span>}
          </button>
        ))}
        <button
          className={`sidebar-feed ${saved ? 'active' : ''}`}
          onClick={() => {
            setSaved(true);
            setFeed(undefined);
          }}
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

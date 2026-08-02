import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Article, FeedList, ListQuery, Me } from '@shared/api';
import { api, setAuthFailureHandler } from './api/client';
import { useArticles } from './api/useArticles';
import { ArticleCard } from './components/ArticleCard';
import { Reader } from './components/Reader';
import { CommandPalette, type Command } from './components/CommandPalette';
import { Digest } from './components/Digest';
import { ShortcutsOverlay } from './components/ShortcutsOverlay';
import { drawFavicon, askForNotificationsOnce, notifyHighScores } from './favicon';
import { isEditableTarget } from './keyboard';
import { useSwipe } from './useSwipe';
import { applyTheme, loadTheme, setTheme, watchSystemTheme, type ThemePreference } from './theme';
import { Toolbar } from './components/Toolbar';
import { ManageFeeds } from './screens/ManageFeeds';
import { Profile } from './screens/Profile';
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
  const [focused, setFocused] = useState(-1);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [showFeeds, setShowFeeds] = useState(false);
  const [theme, setThemeState] = useState<ThemePreference>(() => loadTheme());
  const [reading, setReading] = useState<number | null>(null);
  // At <=720px the carried-over stylesheet parks the sidebar off-screen and
  // waits for `.open`. Carrying CSS across does not carry the JavaScript its
  // rules assume, so without this the sidebar was not merely hidden on a phone
  // -- it was unreachable, and no desktop viewport would ever show that.
  const [drawerOpen, setDrawerOpen] = useState(false);

  // A 401 from anywhere drops straight back to sign-in rather than leaving the
  // reader staring at an empty list.
  useEffect(() => setAuthFailureHandler(() => setSignedIn(false)), []);

  const themeRef = useRef(theme);
  themeRef.current = theme;
  useEffect(() => {
    applyTheme(theme);
    return watchSystemTheme(() => themeRef.current);
  }, [theme]);

  const { articles, loading, error, loadMore, hasMore, patch } = useArticles(
    { feed, saved: saved || undefined, hidden: hidden || undefined, topic,
      sort, limit: 50, reloads } as ListQuery & { reloads: number },
    signedIn === true,
    search,
  );

  useEffect(() => {
    if (signedIn) void api.feeds().then(setFeeds).catch(() => {});
  }, [signedIn, articles.length, reloads]);

  useEffect(() => {
    if (feeds) drawFavicon(feeds.unread);
  }, [feeds, theme]);

  useEffect(() => {
    if (signedIn !== true) return;
    askForNotificationsOnce();
    // The server returns each high scorer once per reader, so polling it is
    // enough -- there is nothing to remember here.
    const tick = () =>
      api.status().then((st) => notifyHighScores(st.high_score)).catch(() => {});
    void tick();
    const id = window.setInterval(tick, 120_000);
    return () => window.clearInterval(id);
  }, [signedIn]);

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

  const rows = articles;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // Ctrl/Cmd-K works while typing; everything else must not.
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setShowPalette(true);
        return;
      }
      if (e.key === 'Escape') {
        setShowPalette(false);
        setShowShortcuts(false);
        setReading(null);
        return;
      }
      if (isEditableTarget(e.target)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      const current = rows[focused];
      switch (e.key) {
        case 'j':
          e.preventDefault();
          setFocused((i) => Math.min(i + 1, rows.length - 1));
          break;
        case 'k':
          e.preventDefault();
          setFocused((i) => Math.max(i - 1, 0));
          break;
        case 'l':
          if (current) void api.vote(current.id, 1).then(patch).catch(() => {});
          break;
        case 's':
          if (current) void api.save(current.id).then(patch).catch(() => {});
          break;
        case 'o':
          if (current) window.open(current.url, '_blank', 'noopener,noreferrer');
          break;
        case 'r':
          if (current) setReading(current.id);
          break;
        case '/':
          e.preventDefault();
          document.getElementById('search')?.focus();
          break;
        case '?':
          setShowShortcuts(true);
          break;
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [rows, focused, patch]);

  useSwipe(
    useCallback((id: number) => { void api.vote(id, 1).then(patch).catch(() => {}); }, [patch]),
    useCallback((id: number) => { void api.dismiss(id).then(patch).catch(() => {}); }, [patch]),
    signedIn === true,
  );

  // A filter change makes the old index meaningless.
  useEffect(() => setFocused(-1), [feed, saved, hidden, topic, search]);

  const commands = useMemo<Command[]>(() => [
    { id: 'all', label: 'Go to all feeds',
      run: () => { setFeed(undefined); setSaved(false); setHidden(false); } },
    { id: 'saved', label: 'Go to saved articles',
      run: () => { setSaved(true); setFeed(undefined); setHidden(false); } },
    { id: 'hidden', label: 'Go to hidden articles',
      run: () => { setHidden(true); setSaved(false); setFeed(undefined); } },
    { id: 'search', label: 'Search articles',
      run: () => document.getElementById('search')?.focus() },
    { id: 'sort-date', label: 'Sort by date', run: () => setSort('date') },
    { id: 'sort-score', label: 'Sort by score', run: () => setSort('score') },
    { id: 'theme-light', label: 'Theme: light', run: () => { setTheme('light'); setThemeState('light'); } },
    { id: 'theme-dark', label: 'Theme: dark', run: () => { setTheme('dark'); setThemeState('dark'); } },
    { id: 'theme-system', label: 'Theme: follow the system', run: () => { setTheme('system'); setThemeState('system'); } },
    { id: 'profile', label: 'Open your profile', run: () => setShowProfile(true) },
    { id: 'feeds', label: 'Manage feeds', run: () => setShowFeeds(true) },
    { id: 'signout', label: 'Sign out', run: () => { void api.logout().finally(() => setSignedIn(false)); } },
    { id: 'shortcuts', label: 'Show keyboard shortcuts', run: () => setShowShortcuts(true) },
    ...(feeds?.feeds ?? []).map((f) => ({
      id: `feed-${f.id}`, label: `Go to ${f.title}`,
      run: () => { setFeed(f.id); setSaved(false); setHidden(false); },
    })),
  ], [feeds]);

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
        <div className="sidebar-footer">
          <button className="btn-icon" title="Your profile" onClick={() => setShowProfile(true)}>
            {me?.username ?? 'Profile'}
          </button>
          <label className="muted" htmlFor="theme-select">Theme</label>
          <select
            id="theme-select"
            value={theme}
            onChange={(e) => {
              const next = e.target.value as ThemePreference;
              setTheme(next);
              setThemeState(next);
            }}
          >
            <option value="system">System</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </div>
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
          {articles.map((a, i) => (
            <ArticleCard
              key={a.id}
              article={a}
              focused={i === focused}
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
      {showProfile && me && <Profile me={me} onClose={() => setShowProfile(false)} />}
      {showFeeds && (
        <ManageFeeds isAdmin={me?.role === 'admin'} onClose={() => {
          setShowFeeds(false);
          setReloads((n) => n + 1);   // feeds may have changed the list
        }} />
      )}
      {showShortcuts && <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />}
      {showPalette && (
        <CommandPalette commands={commands} onClose={() => setShowPalette(false)} />
      )}
    </div>
  );
}

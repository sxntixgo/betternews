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
import { watchConnectivity } from './pwa';
import { useSwipe } from './useSwipe';
import { applyTheme, loadTheme, setTheme, watchSystemTheme, type ThemePreference } from './theme';
import { applyDensity, loadDensity, setDensity, type Density } from './density';
import { Toolbar } from './components/Toolbar';
import { Sidebar } from './components/Sidebar';
import { ManageFeeds } from './screens/ManageFeeds';
import { Profile } from './screens/Profile';
import { Settings } from './screens/Settings';
import { AdminUsers } from './screens/AdminUsers';
import { CallLog } from './screens/CallLog';
import { Insights } from './screens/Insights';
import { SignIn } from './screens/SignIn';
import { ForcedPasswordChange } from './screens/ForcedPasswordChange';
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
  const [showDigest, setShowDigest] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [showFeeds, setShowFeeds] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showUsers, setShowUsers] = useState(false);
  const [showInsights, setShowInsights] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [theme, setThemeState] = useState<ThemePreference>(() => loadTheme());
  const [density, setDensityState] = useState<Density>(() => loadDensity());
  useEffect(() => applyDensity(density), [density]);
  const [reading, setReading] = useState<number | null>(null);
  // At <=720px the carried-over stylesheet parks the sidebar off-screen and
  // waits for `.open`. Carrying CSS across does not carry the JavaScript its
  // rules assume, so without this the sidebar was not merely hidden on a phone
  // -- it was unreachable, and no desktop viewport would ever show that.
  const [drawerOpen, setDrawerOpen] = useState(false);
  // `.offline-bar` was carried over from the server stylesheet and styled all
  // this time with nothing to show it.
  const [online, setOnline] = useState(true);
  useEffect(() => watchConnectivity(setOnline), []);

  // A 401 from anywhere drops straight back to sign-in rather than leaving the
  // reader staring at an empty list.
  useEffect(() => setAuthFailureHandler(() => setSignedIn(false)), []);

  const themeRef = useRef(theme);
  themeRef.current = theme;
  useEffect(() => {
    applyTheme(theme);
    return watchSystemTheme(() => themeRef.current);
  }, [theme]);

  const { articles, diagnosis, loading, error, loadMore, hasMore, patch } = useArticles(
    { feed, saved: saved || undefined, hidden: hidden || undefined, topic,
      sort, limit: 50, reloads } as ListQuery & { reloads: number },
    signedIn === true,
    search,
  );

  /**
   * The dismissed pile: the same list, asked for separately.
   *
   * A second `useArticles` rather than a flag threaded through the first. They
   * page independently -- you can be four pages into the unread list and one
   * page into the dismissed one -- and one hook holding two offsets and two
   * end-of-list flags would be the same two lists with the seam hidden.
   *
   * `enabled` is what makes the button a button: nothing is fetched until the
   * reader asks, so the common case costs no request at all.
   */
  const [showDismissed, setShowDismissed] = useState(false);
  const pile = useArticles(
    { feed, saved: saved || undefined, hidden: hidden || undefined, topic,
      sort, limit: 50, dismissed: true, reloads } as ListQuery & { reloads: number },
    signedIn === true && showDismissed,
    '',
  );

  // Searching and the Hidden view are their own answers to "what should I look
  // at"; a dismissed pile underneath them is noise. It also resets on any
  // filter change, so the button does not stay open over a list it was never
  // opened for.
  const offersDismissed = !search && !hidden;
  useEffect(() => {
    setShowDismissed(false);
  }, [feed, saved, hidden, topic, search]);

  /**
   * An updated article can belong to either list, so offer it to both.
   *
   * `patch` maps over its own rows and replaces by id, so the list that does
   * not hold the article is unchanged -- cheaper and far less brittle than
   * working out which list a card came from and threading that down.
   */
  const patchBoth = useCallback((updated: Article) => {
    patch(updated);
    pile.patch(updated);
  }, [patch, pile.patch]);  // eslint-disable-line react-hooks/exhaustive-deps

  // One scroll, two lists. The sentinel feeds the unread list until it runs
  // out, then the pile -- which is what "keeps loading as the user scrolls"
  // has to mean when the reader has already opened it.
  const moreToLoad = hasMore || (showDismissed && pile.hasMore);
  const loadNext = useCallback(() => {
    if (hasMore) loadMore();
    else if (showDismissed) pile.loadMore();
  }, [hasMore, loadMore, showDismissed, pile.loadMore]);  // eslint-disable-line react-hooks/exhaustive-deps

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
      if (!node || !moreToLoad) return;
      const io = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) loadNext();
      });
      io.observe(node);
      return () => io.disconnect();
    },
    [moreToLoad, loadNext],
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
        setShowDigest(false);
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
        case 'd':
          if (current) void api.vote(current.id, -1).then(patch).catch(() => {});
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
        case 'D':
          e.preventDefault();
          void api.dismissAll({ feed, saved: saved || undefined,
                                hidden: hidden || undefined, topic })
            .then(() => setReloads((n) => n + 1))
            .catch(() => {});
          break;
        case 'w':
          setShowDigest(true);
          break;
        case '/': {
          e.preventDefault();
          // The field is behind a button at phone width, and focusing a hidden
          // input silently does nothing -- so open it the way a reader would.
          // Asked of the element rather than of the viewport: whether it is on
          // screen is a CSS decision, and this should not hold a second copy
          // of it.
          const box = document.getElementById('search') as HTMLInputElement | null;
          if (box && box.offsetParent !== null) box.focus();
          else document.querySelector<HTMLButtonElement>('.search-toggle')?.click();
          break;
        }
        case '?':
          setShowShortcuts(true);
          break;
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [rows, focused, patch, feed, saved, hidden, topic]);

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
    { id: 'density', label: 'Toggle compact list (hides summaries and tags)',
      run: () => {
        const next = density === 'compact' ? 'comfortable' : 'compact';
        setDensity(next);
        setDensityState(next);
      } },
    { id: 'theme-light', label: 'Theme: light', run: () => { setTheme('light'); setThemeState('light'); } },
    { id: 'theme-dark', label: 'Theme: dark', run: () => { setTheme('dark'); setThemeState('dark'); } },
    { id: 'theme-system', label: 'Theme: follow the system', run: () => { setTheme('system'); setThemeState('system'); } },
    { id: 'profile', label: 'Open your profile', run: () => setShowProfile(true) },
    { id: 'feeds', label: 'Manage feeds', run: () => setShowFeeds(true) },
    // Offered only to an admin. Every endpoint behind it checks again -- this
    // is about not showing a reader a door that answers 403.
    ...(me?.role === 'admin'
      ? [
          { id: 'settings', label: 'Open settings', run: () => setShowSettings(true) },
          { id: 'users', label: 'Manage users', run: () => setShowUsers(true) },
          { id: 'insights', label: 'Open insights', run: () => setShowInsights(true) },
          { id: 'ollama-log', label: 'Open the Ollama log', run: () => setShowLog(true) },
        ]
      : []),
    { id: 'signout', label: 'Sign out', run: () => { void api.logout().finally(() => setSignedIn(false)); } },
    { id: 'shortcuts', label: 'Show keyboard shortcuts', run: () => setShowShortcuts(true) },
    ...(feeds?.feeds ?? []).map((f) => ({
      id: `feed-${f.id}`, label: `Go to ${f.title}`,
      run: () => { setFeed(f.id); setSaved(false); setHidden(false); },
    })),
  ], [feeds, me, density]);

  if (signedIn === null) return <p className="loading">Loading…</p>;
  if (!signedIn) return <SignIn onDone={() => setSignedIn(true)} />;
  // Before anything else a reset account can reach. The server used to enforce
  // this with an app-wide redirect to the profile page; with that UI gone, this
  // is the only thing between a reset password and the reading list.
  if (me?.must_change_password) {
    return (
      <ForcedPasswordChange
        username={me.username}
        // null, not true: it re-runs the /me effect, which is what clears the
        // flag here. It also covers the sign-out button, whose /me then 401s.
        onDone={() => setSignedIn(null)}
      />
    );
  }

  // Maps the server's diagnosis to a screen. The server names a label, not a
  // URL: it has no idea this client is modal-based rather than page-based.
  function runDiagnosisAction(kind: string) {
    if (kind === 'no_feeds') return setShowFeeds(true);
    if (kind === 'all_hidden') return setHidden(true);
    // Same call the toolbar's Refresh makes; the list refetches when it lands.
    if (kind === 'not_polled') {
      void api.poll().then(() => setReloads((n) => n + 1)).catch(() => {});
      return;
    }
    return setShowSettings(true);   // every Ollama and model problem
  }

  const vote = (a: Article, value: 1 | -1) =>
    api.vote(a.id, value).then(patchBoth).catch(() => {});
  const save = (a: Article) => api.save(a.id).then(patchBoth).catch(() => {});

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
        <div className="sidebar-scroll">
        <Sidebar
          feeds={feeds}
          feed={feed}
          saved={saved}
          hidden={hidden}
          onAll={() => choose(() => { setFeed(undefined); setSaved(false); setHidden(false); })}
          onFeed={(id) => choose(() => { setFeed(id); setSaved(false); setHidden(false); })}
          onSaved={() => choose(() => { setSaved(true); setFeed(undefined); setHidden(false); })}
          onHidden={() => choose(() => { setHidden(true); setSaved(false); setFeed(undefined); })}
          onHiddenFeed={(id) => choose(() => { setHidden(true); setSaved(false); setFeed(id); })}
          onManageFeeds={me?.role === 'admin' ? () => setShowFeeds(true) : undefined}
        />
        </div>
        <div className="sidebar-footer">
          {/* Every one of these was reachable only through the command palette,
              which meant the app's whole admin surface was behind a keyboard
              shortcut you had to already know existed. The server UI had the
              same icons in the same corner. */}
          {me?.role === 'admin' && (
            <div className="sidebar-tools">
              <IconButton label="Settings" onClick={() => setShowSettings(true)}
                          d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
              <IconButton label="Users" onClick={() => setShowUsers(true)}
                          d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M22 21v-2a4 4 0 0 0-3-3.9 M16 3.1a4 4 0 0 1 0 7.8" />
              <IconButton label="Insights" onClick={() => setShowInsights(true)}
                          d="M3 3v18h18 M7 15l4-4 3 3 5-6" />
              <IconButton label="Ollama log" onClick={() => setShowLog(true)}
                          d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z M14 2v6h6 M8 13h8 M8 17h5" />
            </div>
          )}
          <div className="sidebar-tools">
            {/* Icon on a phone, name on a desktop. In the packed footer row the
                name was squeezed between the icons and rendered as "eade",
                which reads as breakage rather than as a username. */}
            <button className="btn-icon btn-labelled sidebar-username"
                    title={`Your profile — ${me?.username ?? ''}`}
                    aria-label={`Your profile: ${me?.username ?? 'account'}`}
                    onClick={() => setShowProfile(true)}>
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                <path fill="none" stroke="currentColor" strokeWidth="1.8"
                      strokeLinecap="round" strokeLinejoin="round"
                      d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8" />
              </svg>
              <span className="btn-label">{me?.username ?? 'Profile'}</span>
            </button>
            <IconButton label="Keyboard shortcuts" onClick={() => setShowShortcuts(true)}
                        d="M2 6h20v12H2z M6 10h.01 M10 10h.01 M14 10h.01 M18 10h.01 M8 14h8" />
            <IconButton label="Sign out"
                        onClick={() => { void api.logout().finally(() => setSignedIn(false)); }}
                        d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9" />
          </div>
          {/* Three icons, not a dropdown: it is a three-state preference used
              often enough that opening a menu to change it is a step too many.
              System is a monitor, not "auto", because what it follows is the
              machine's setting. */}
          <div className="theme-picker" role="radiogroup" aria-label="Theme">
            {THEMES.map(({ value, label, d }) => (
              <button
                key={value}
                className={`btn-icon ${theme === value ? 'active' : ''}`}
                role="radio"
                aria-checked={theme === value}
                title={label}
                aria-label={label}
                onClick={() => { setTheme(value); setThemeState(value); }}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                  <path fill="none" stroke="currentColor" strokeWidth="1.8"
                        strokeLinecap="round" strokeLinejoin="round" d={d} />
                </svg>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <main className="site-content">
        {!online && (
          <div className="offline-bar" role="status">
            Offline — showing what is already loaded. Votes and saves will fail
            until you reconnect.
          </div>
        )}
        <header className="site-header">
          <Toolbar
            search={search}
            onSearch={setSearch}
            sort={sort}
            onSort={setSort}
            density={density}
            onDensity={(d) => { setDensity(d); setDensityState(d); }}
            canPoll={me?.role === 'admin'}
            onRefreshed={() => setReloads((n) => n + 1)}
            onDigest={() => setShowDigest(true)}
            onDismissAll={async () => {
              await api.dismissAll({ feed, saved: saved || undefined,
                                     hidden: hidden || undefined, topic });
              setReloads((n) => n + 1);
            }}
          />
        </header>

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
              // The shell already holds the feed list for the sidebar; the article
              // itself only carries feed_id.
              feedName={feeds?.feeds.find((f) => f.id === a.feed_id)?.title}
            />
          ))}
          {loading && <p className="loading">Loading…</p>}
          {!loading && articles.length === 0 && !error && (
            // The server says why. "Nothing to read" on its own is how a
            // misconfigured model went unnoticed three times.
            diagnosis ? (
              <div className={`empty diagnosis diagnosis-${diagnosis.kind}`}>
                <h2>{diagnosis.title}</h2>
                <p>{diagnosis.detail}</p>
                {/* Withheld from a plain reader: there is nothing they can do
                    about an unreachable Ollama, and a button that 403s reads
                    as breakage rather than as a permission. */}
                {diagnosis.action && (!diagnosis.admin_only || me?.role === 'admin') && (
                  <button onClick={() => runDiagnosisAction(diagnosis.kind)}>
                    {diagnosis.action}
                  </button>
                )}
              </div>
            ) : (
              <p className="empty">Nothing to read.</p>
            )
          )}
          {/* The dismissed pile, under everything else and behind a press.
              Only offered once the unread list has actually run out -- a
              button to load more of what you have dealt with, above things you
              have not, would be in the way. */}
          {offersDismissed && !hasMore && !loading && (
            showDismissed ? (
              <>
                <h2 className="pile-heading">Dismissed</h2>
                {pile.articles.map((a) => (
                  <ArticleCard
                    key={a.id}
                    article={a}
                    onOpen={(x) => setReading(x.id)}
                    onVote={vote}
                    onSave={save}
                    onTopic={(t) => { setTopic(t); setSearch(''); }}
                    // The shell already holds the feed list for the sidebar; the article
                    // itself only carries feed_id.
                    feedName={feeds?.feeds.find((f) => f.id === a.feed_id)?.title}
                  />
                ))}
                {pile.loading && <p className="loading">Loading…</p>}
                {!pile.loading && pile.articles.length === 0 && (
                  <p className="empty">Nothing dismissed.</p>
                )}
              </>
            ) : (
              <button className="pile-toggle" onClick={() => setShowDismissed(true)}>
                Show dismissed articles
              </button>
            )
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
      {showSettings && me?.role === 'admin' && (
        <Settings onClose={() => {
          setShowSettings(false);
          setReloads((n) => n + 1);   // de-clickbait and padding change the list
        }} />
      )}
      {showUsers && me?.role === 'admin' && (
        <AdminUsers onClose={() => setShowUsers(false)} />
      )}
      {showInsights && me?.role === 'admin' && (
        <Insights onClose={() => setShowInsights(false)} />
      )}
      {showLog && me?.role === 'admin' && <CallLog onClose={() => setShowLog(false)} />}
      {showDigest && <Digest onClose={() => setShowDigest(false)} />}
      {showShortcuts && <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />}
      {showPalette && (
        <CommandPalette commands={commands} onClose={() => setShowPalette(false)} />
      )}
    </div>
  );
}

/** A labelled icon button. `label` is both the tooltip and the accessible name,
 *  so an icon-only control is never nameless to a screen reader. */
function IconButton({ label, d, onClick }: {
  label: string; d: string; onClick: () => void;
}) {
  return (
    <button className="btn-icon" title={label} aria-label={label} onClick={onClick}>
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <path fill="none" stroke="currentColor" strokeWidth="1.8"
              strokeLinecap="round" strokeLinejoin="round" d={d} />
      </svg>
    </button>
  );
}

/** System, light and dark. `d` is the icon path; the label is both tooltip and
 *  accessible name. */
const THEMES: { value: ThemePreference; label: string; d: string }[] = [
  { value: 'system', label: 'Follow the system',
    d: 'M3 4h18v12H3z M8 20h8 M12 16v4' },
  { value: 'light', label: 'Light',
    d: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z M12 2v2 M12 20v2 M2 12h2 M20 12h2 '
       + 'M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4' },
  { value: 'dark', label: 'Dark',
    d: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z' },
];

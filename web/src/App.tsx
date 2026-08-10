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
          { id: 'settings', label: 'Open server settings', run: () => setShowSettings(true) },
          { id: 'users', label: 'Manage users', run: () => setShowUsers(true) },
          { id: 'insights', label: 'Open your stats', run: () => setShowInsights(true) },
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

      {/* Five sections, in the order a reader reaches for them: what to read,
          what they kept, how it looks, who they are, and what only an
          administrator touches. It used to be one undivided list of feeds with
          an unlabelled tray of icons underneath, so "where do I change the
          theme" had no answer you could arrive at by looking. */}
      <aside className={`sidebar ${drawerOpen ? 'open' : ''}`}>
        <div className="sidebar-brand">Better News</div>
        <div className="sidebar-scroll">

          <section className="sidebar-section">
            <h2 className="sidebar-section-title">Feeds</h2>
            <Sidebar
              feeds={feeds}
              feed={feed}
              saved={saved}
              hidden={hidden}
              onAll={() => choose(() => { setFeed(undefined); setSaved(false); setHidden(false); })}
              onFeed={(id) => choose(() => { setFeed(id); setSaved(false); setHidden(false); })}
              onHidden={() => choose(() => { setHidden(true); setSaved(false); setFeed(undefined); })}
              onHiddenFeed={(id) => choose(() => { setHidden(true); setSaved(false); setFeed(id); })}
              onManageFeeds={me?.role === 'admin' ? () => setShowFeeds(true) : undefined}
            />
          </section>

          <section className="sidebar-section">
            <h2 className="sidebar-section-title">Saved</h2>
            <button
              className={`sidebar-feed ${saved ? 'active' : ''}`}
              onClick={() => choose(() => { setSaved(true); setFeed(undefined); setHidden(false); })}
            >
              <span className="sidebar-feed-title">Saved articles</span>
              {feeds && feeds.saved > 0 && (
                <span className="pill sidebar-feed-count">{feeds.saved}</span>
              )}
            </button>
          </section>

          {/* Display preferences, and all of them per-device on purpose: the
              right density on a phone is not the right one on a desktop. These
              two toggles used to live in the top bar, where on a 390px screen
              they cost a whole second row of a header that was already a
              quarter of the viewport. */}
          <section className="sidebar-section">
            <h2 className="sidebar-section-title">Settings</h2>

            <div className="sidebar-row">
              <span className="switch-label">Compact</span>
              <button
                className="switch"
                role="switch"
                aria-checked={density === 'compact'}
                aria-label="Compact list"
                title="Compact list — hides summaries and tags"
                onClick={() => {
                  const next = density === 'compact' ? 'comfortable' : 'compact';
                  setDensity(next); setDensityState(next);
                }}
              >
                <span className="switch-track"><span className="switch-knob" /></span>
              </button>
            </div>

            {/* One control with two states, not two buttons that happen to be
                adjacent. Date is the default and the left-hand position, so the
                knob resting at "off" means newest-first. */}
            {/* "Date" used to sit hard left with the knob and "Score" pushed to
                the right edge, so the row read as three separate things. The
                two state names belong beside the knob that moves between
                them; "Sort" is the row's label, like every other row here. */}
            <div className="sidebar-row">
              <span className="switch-label">Sort</span>
              <button
                className="switch"
                role="switch"
                aria-checked={sort === 'score'}
                aria-label="Sort by score instead of date"
                onClick={() => setSort(sort === 'score' ? 'date' : 'score')}
              >
                <span className="switch-label">Date</span>
                <span className="switch-track"><span className="switch-knob" /></span>
                <span className="switch-label">Score</span>
              </button>
            </div>

            {/* Three icons, not a dropdown: it is a three-state preference used
                often enough that opening a menu to change it is a step too many.
                System is a monitor, not "auto", because what it follows is the
                machine's setting. */}
            {/* Labelled like the toggles above it. As a bare row of three icons
                in a list of named settings, the one thing it did not say was
                what it was for. */}
            <div className="sidebar-row">
            <span className="switch-label">Theme</span>
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

            <button className="sidebar-item" onClick={() => setShowShortcuts(true)}>
              Keyboard shortcuts
            </button>
          </section>

          <section className="sidebar-section">
            <h2 className="sidebar-section-title">You</h2>
            <button className="sidebar-item" onClick={() => setShowProfile(true)}>
              {me?.username ? `Profile — ${me.username}` : 'Profile'}
            </button>
            {/* Ranking accuracy: how often the score agreed with the reader.
                Filed here rather than under Admin because it is a statement
                about this reader's taste, not about the server -- though the
                endpoint is still admin-only, so a plain reader is not offered
                a button that would answer 403. */}
            {me?.role === 'admin' && (
              <button className="sidebar-item" onClick={() => setShowInsights(true)}>
                Your stats
              </button>
            )}
            <button
              className="sidebar-item"
              onClick={() => { void api.logout().finally(() => setSignedIn(false)); }}
            >
              Sign out
            </button>
          </section>

          {/* Hiding a control is not gating an endpoint -- every one of these is
              behind `@api_admin` as well, and `tests/test_api.py` asserts a
              plain reader gets a JSON 403 from each. This is only about not
              offering a button that cannot work. */}
          {me?.role === 'admin' && (
            <section className="sidebar-section">
              <h2 className="sidebar-section-title">Admin</h2>
              <button className="sidebar-item" onClick={() => setShowUsers(true)}>Users</button>
              <button className="sidebar-item" onClick={() => setShowSettings(true)}>
                Server settings
              </button>
              <button className="sidebar-item" onClick={() => setShowLog(true)}>Ollama log</button>
            </section>
          )}
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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { isNetworkError } from '@shared/api';
import type { Article, DigestMeta, FeedList, ListQuery, Me } from '@shared/api';
import { api, setAuthFailureHandler } from './api/client';
import { useArticles } from './api/useArticles';
import { ArticleCard } from './components/ArticleCard';
import { SingleStory } from './components/SingleStory';
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
import { applyPhotos, loadPhotos, setPhotos, type Photos } from './photos';
import { Toolbar } from './components/Toolbar';
import { Toggle } from './components/Toggle';
import { Segmented } from './components/Segmented';
import { Sidebar, HiddenFeeds } from './components/Sidebar';
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
  // Distinct from `signedIn === false`. A server this browser cannot reach is
  // not a signed-out reader, and conflating the two is how an untrusted
  // certificate on a phone presented itself as a rejected password: /me failed
  // at the transport layer, the shell concluded "signed out", and the sign-in
  // form it offered could not reach the server either.
  const [unreachable, setUnreachable] = useState(false);
  const [retries, setRetries] = useState(0);
  useEffect(() => {
    // Re-runs when signedIn flips, not just on mount: the first call 401s while
    // signed out, and without asking again after login the app never learns who
    // the reader is -- so admin-only controls stay hidden for an admin.
    if (signedIn === false) return;
    api.me()
      .then((u) => { setMe(u); setSignedIn(true); setUnreachable(false); })
      .catch((e: unknown) => {
        if (isNetworkError(e)) setUnreachable(true);
        else { setUnreachable(false); setSignedIn(false); }
      });
  }, [signedIn, retries]);
  const [feeds, setFeeds] = useState<FeedList | null>(null);
  const [digestMeta, setDigestMeta] = useState<DigestMeta | null>(null);
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
  const [photos, setPhotosState] = useState<Photos>(() => loadPhotos());
  useEffect(() => applyPhotos(photos), [photos]);
  const [reading, setReading] = useState<number | null>(null);
  // Single-story mode: App.tsx owns both the switch and the index, per the
  // task 11 brief -- SingleStory itself holds no state about which story it
  // is showing.
  const [singleStoryMode, setSingleStoryMode] = useState(false);
  const [singleIndex, setSingleIndex] = useState(0);
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
    // Once per sign-in, not on every reload: `/digest/meta` records the visit
    // (`repo.users.touch_last_seen`) as a side effect of being asked, so
    // calling it repeatedly would keep pushing "since Friday" toward "since
    // now". It never generates the briefing itself -- that's still only
    // `GET /digest`, opened on demand -- so this is cheap on every page load.
    if (signedIn) void api.digestMeta().then(setDigestMeta).catch(() => {});
  }, [signedIn]);

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
    { id: 'photos', label: 'Toggle article photos',
      run: () => setPhotosState((p) => { const n = p === 'on' ? 'off' : 'on'; setPhotos(n); return n; }) },
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

  // Checked before "signed out", because a page served from the service
  // worker's cache looks identical to a live one: `navigator.onLine` is true on
  // a phone that has wifi but cannot reach *this* server, so nothing else here
  // would say the app is talking to no one.
  if (unreachable) {
    return (
      <div className="unreachable" role="alert">
        <h1>Can't reach Better News</h1>
        <p>
          This page loaded from an offline copy. Signing in, and everything
          else, needs a working connection to the server.
        </p>
        <button type="button" onClick={() => setRetries((n) => n + 1)}>
          Try again
        </button>
      </div>
    );
  }
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

  // What the compact header calls the current list -- the same choice the
  // sidebar highlights, spelled out for a reader who has not opened it.
  const headerTitle = saved
    ? 'Saved articles'
    : hidden
      ? 'Hidden'
      : feed
        ? (feeds?.feeds.find((f) => f.id === feed)?.title ?? 'Feed')
        : 'All feeds';

  return (
    <div className="site-layout">
      <div
        className={`drawer-scrim ${drawerOpen ? 'visible' : ''}`}
        onClick={() => setDrawerOpen(false)}
      />

      {/* Three groups, a settings block and a footer -- no headings at all.
          It was five all-caps labelled sections (FEEDS / SAVED / SETTINGS /
          YOU / ADMIN), and with six rows under some of them the labels were
          most of the drawer's ink. What groups the rows now is the space
          between the groups and, for the feeds, the indent rule their
          children hang behind. */}
      <aside className={`sidebar ${drawerOpen ? 'open' : ''}`}>
        {/* The one part that scrolls, and it holds everything: on a phone the
            drawer is taller than the screen, so a head or a footer pinned
            outside this would be a band the reader cannot scroll past. */}
        <div className="sidebar-scroll">
          <div className="drawer-head">
            <div className="drawer-wordmark">Better News</div>
            {/* Who is reading and how much is waiting -- the two facts the
                five section headers never told anyone. */}
            <div className="drawer-sub">
              {me?.username ?? 'Reader'} · {feeds?.unread ?? 0} unread
            </div>
          </div>

          <div className="drawer-groups">
            {/* 1. What to read. */}
            <div className="drawer-group">
              <Sidebar
                feeds={feeds}
                feed={feed}
                saved={saved}
                hidden={hidden}
                onAll={() => choose(() => { setFeed(undefined); setSaved(false); setHidden(false); })}
                onFeed={(id) => choose(() => { setFeed(id); setSaved(false); setHidden(false); })}
                onManageFeeds={me?.role === 'admin' ? () => setShowFeeds(true) : undefined}
              />
            </div>

            {/* 2. The lists that are not the reading list: what the reader
                kept, what was kept from them, and how well the score has been
                guessing. Saved and Hidden were two sections of one row each. */}
            <div className="drawer-group">
              <button
                className={`sidebar-feed ${saved ? 'active' : ''}`}
                onClick={() => choose(() => { setSaved(true); setFeed(undefined); setHidden(false); })}
              >
                <span className="sidebar-feed-title">Saved articles</span>
                {feeds && feeds.saved > 0 && (
                  <span className="pill sidebar-feed-count count">{feeds.saved}</span>
                )}
              </button>

              <HiddenFeeds
                feeds={feeds}
                feed={feed}
                hidden={hidden}
                onHidden={() => choose(() => { setHidden(true); setSaved(false); setFeed(undefined); })}
                onHiddenFeed={(id) => choose(() => { setHidden(true); setSaved(false); setFeed(id); })}
              />

              {/* The single-story entry point (task 11). A visible control,
                  not a command-palette entry -- design-system.spec asserts
                  nothing in this app is reachable only through the palette.
                  Resets the index so entry always starts at story one. */}
              <button
                className="sidebar-feed"
                onClick={() => choose(() => { setSingleStoryMode(true); setSingleIndex(0); })}
              >
                <span className="sidebar-feed-title">One at a time</span>
              </button>

              {/* Ranking accuracy: how often the score agreed with the reader.
                  Filed with the reader's own lists rather than with the admin
                  links because it is a statement about this reader's taste --
                  though the endpoint is still admin-only, so a plain reader is
                  not offered a button that would answer 403. */}
              {me?.role === 'admin' && (
                <button className="drawer-item" onClick={() => setShowInsights(true)}>
                  Your stats
                </button>
              )}
            </div>

            {/* 3. Display preferences, and all of them per-device on purpose:
                the right density on a phone is not the right one on a desktop.
                Task 9 replaces the controls in here; the container is what it
                depends on. */}
            <div className="drawer-group drawer-settings">
              <Toggle
                label="Photos"
                name="Show photos"
                checked={photos === 'on'}
                onChange={(v) => {
                  const next = v ? 'on' : 'off';
                  setPhotos(next); setPhotosState(next);
                }}
              />

              <Toggle
                label="Compact"
                name="Compact list"
                checked={density === 'compact'}
                onChange={(v) => {
                  const next = v ? 'compact' : 'comfortable';
                  setDensity(next); setDensityState(next);
                }}
              />

              {/* Was one switch, "sort by score instead of date". A radiogroup
                  says the same thing without the double negative: Date and
                  Score are two positions, not an on/off toggle. */}
              <Segmented
                label="Sort"
                value={sort}
                options={[
                  { value: 'score', label: 'Score' },
                  { value: 'date', label: 'Date' },
                ]}
                onChange={setSort}
              />

              {/* Three positions, not a dropdown: a three-state preference
                  used often enough that opening a menu to change it is a step
                  too many. The system option is visibly "Auto" -- it used to
                  be an unlabelled icon -- but keeps its old accessible name
                  ("Follow the system") via Segmented's `name` override, since
                  interaction.spec.ts still finds it by that. */}
              <Segmented
                label="Theme"
                value={theme}
                options={[
                  { value: 'system', label: 'Auto', name: 'Auto — follow the system' },
                  { value: 'light', label: 'Light' },
                  { value: 'dark', label: 'Dark' },
                ]}
                onChange={(v) => { setTheme(v); setThemeState(v); }}
              />
            </div>
          </div>

          <div className="drawer-divider" />

          {/* Everything that opens a dialog rather than filtering the list,
              as small text at the foot of the column. The three admin entries
              are here by name rather than behind one "Admin" word: every
              action needs its own visible control, and design-system.spec
              asserts each of these is clickable without the palette. Hiding a
              control is not gating an endpoint -- all three are behind
              `@api_admin` as well, and tests/test_api.py asserts a plain
              reader gets a JSON 403 from each. */}
          <div className="drawer-footer">
            <button className="drawer-link" onClick={() => setShowProfile(true)}>
              {me?.username ? `Profile — ${me.username}` : 'Profile'}
            </button>
            {me?.role === 'admin' && (
              <>
                <button className="drawer-link" onClick={() => setShowUsers(true)}>Users</button>
                <button className="drawer-link" onClick={() => setShowSettings(true)}>
                  Server settings
                </button>
                <button className="drawer-link" onClick={() => setShowLog(true)}>Ollama log</button>
              </>
            )}
            <button className="drawer-link" onClick={() => setShowShortcuts(true)}>
              Keyboard shortcuts
            </button>
            <button
              className="drawer-link"
              onClick={() => { void api.logout().finally(() => setSignedIn(false)); }}
            >
              Sign out
            </button>
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
        {/* Single-story mode replaces the header, the missed strip and the
            list with one full-height dark shell -- an alternative to the
            list, not layered on top of it. The drawer and its "One at a
            time" entry point are untouched, so `Feeds` here (or running out
            of stories) is the only way back. */}
        {singleStoryMode ? (
          <SingleStory
            articles={rows}
            index={singleIndex}
            feedName={(a) => feeds?.feeds.find((f) => f.id === a.feed_id)?.title}
            onAdvance={setSingleIndex}
            onVote={vote}
            onOpen={(a) => setReading(a.id)}
            onExit={() => setSingleStoryMode(false)}
          />
        ) : (
          <>
            <header className="site-header">
              <Toolbar
                drawerOpen={drawerOpen}
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
                title={headerTitle}
                unread={feeds?.unread ?? 0}
                onOpenDrawer={() => setDrawerOpen((v) => !v)}
              />
            </header>

            {/* The briefing's trigger, not the briefing itself -- Digest still
                fetches the briefing body only when opened. The subtitle comes from
                `digestMeta` (`GET /digest/meta`), which answers counts and the
                previous-visit weekday without generating anything; that's a
                separate endpoint from `GET /digest` specifically so this strip
                never costs an LLM call. Hidden with nothing missed: `since_label`
                is null before the first visit ever recorded one, in which case the
                subtitle falls back to a plain unread count. */}
            {digestMeta && digestMeta.story_count > 0 && (
              <div className="missed-strip">
                <div className="missed-text">
                  <div className="missed-title">What you missed</div>
                  <div className="missed-sub">
                    {digestMeta.since_label
                      ? `${digestMeta.story_count} stories since ${digestMeta.since_label} · ${digestMeta.read_minutes} min summary`
                      : `${digestMeta.story_count} unread`}
                  </div>
                </div>
                <button className="missed-cta" onClick={() => setShowDigest(true)}>Read</button>
              </div>
            )}

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
          </>
        )}
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


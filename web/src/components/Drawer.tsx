import type { Dispatch, SetStateAction } from 'react';
import type { FeedList, Me } from '@shared/api';
import { api } from '../api/client';
import { setDensity, type Density } from '../density';
import { setPhotos, type Photos } from '../photos';
import { setTheme, type ThemePreference } from '../theme';
import { Toggle } from './Toggle';
import { Segmented } from './Segmented';
import { Sidebar, HiddenFeeds } from './Sidebar';

interface DrawerProps {
  drawerOpen: boolean;
  me: Me | null;
  feeds: FeedList | null;
  feed: number | undefined;
  saved: boolean;
  hidden: boolean;
  photos: Photos;
  density: Density;
  sort: 'date' | 'score';
  theme: ThemePreference;
  // Choosing anything closes the drawer: on a phone the list is behind it.
  choose: (fn: () => void) => void;
  setFeed: Dispatch<SetStateAction<number | undefined>>;
  setSaved: Dispatch<SetStateAction<boolean>>;
  setHidden: Dispatch<SetStateAction<boolean>>;
  setSingleStoryMode: Dispatch<SetStateAction<boolean>>;
  setSingleIndex: Dispatch<SetStateAction<number>>;
  setShowFeeds: Dispatch<SetStateAction<boolean>>;
  setShowInsights: Dispatch<SetStateAction<boolean>>;
  setPhotosState: Dispatch<SetStateAction<Photos>>;
  setDensityState: Dispatch<SetStateAction<Density>>;
  setSort: Dispatch<SetStateAction<'date' | 'score'>>;
  setThemeState: Dispatch<SetStateAction<ThemePreference>>;
  setShowProfile: Dispatch<SetStateAction<boolean>>;
  setShowUsers: Dispatch<SetStateAction<boolean>>;
  setShowSettings: Dispatch<SetStateAction<boolean>>;
  setShowLog: Dispatch<SetStateAction<boolean>>;
  setShowShortcuts: Dispatch<SetStateAction<boolean>>;
  setSignedIn: Dispatch<SetStateAction<boolean | null>>;
}

/**
 * The navigation drawer: on a phone it slides in over the list, on a desktop
 * it is a permanent 262px sidebar. Extracted verbatim out of `App.tsx`, which
 * still owns every piece of state and every handler here -- this component
 * holds none of its own.
 */
export function Drawer({
  drawerOpen, me, feeds, feed, saved, hidden, photos, density, sort, theme,
  choose, setFeed, setSaved, setHidden, setSingleStoryMode, setSingleIndex,
  setShowFeeds, setShowInsights, setPhotosState, setDensityState, setSort,
  setThemeState, setShowProfile, setShowUsers, setShowSettings, setShowLog,
  setShowShortcuts, setSignedIn,
}: DrawerProps) {
  return (
    // Three groups, a settings block and a footer -- no headings at all.
    // It was five all-caps labelled sections (FEEDS / SAVED / SETTINGS /
    // YOU / ADMIN), and with six rows under some of them the labels were
    // most of the drawer's ink. What groups the rows now is the space
    // between the groups and, for the feeds, the indent rule their
    // children hang behind.
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
                <span className="sidebar-feed-count">{feeds.saved}</span>
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
  );
}

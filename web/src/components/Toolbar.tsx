import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

/**
 * Refresh, dismiss, the briefing and search.
 *
 * The density and sort toggles moved into the drawer's Settings section. They
 * are preferences, set once and left; here they cost a whole second row of a
 * header that was already a quarter of a phone's viewport.
 *
 * Refresh is the interesting one: POST /poll returns immediately because the
 * work runs in a background thread, so the button would look inert for minutes.
 * It polls /status instead and only settles once last_pipeline_run_at advances,
 * which is what the server-rendered UI does.
 */
export function Toolbar({
  search,
  onSearch,
  onDismissAll,
  onDigest,
  onRefreshed,
  canPoll,
  title,
  unread,
  onOpenDrawer,
}: {
  search: string;
  onSearch: (q: string) => void;
  onDismissAll: () => void;
  onDigest: () => void;
  onRefreshed: () => void;
  canPoll: boolean;
  title: string;
  unread: number;
  onOpenDrawer: () => void;
}) {
  const [polling, setPolling] = useState(false);
  const [text, setText] = useState(search);
  const timer = useRef<number | undefined>(undefined);
  // Opening the field and then having to tap it again would make this two taps
  // where the always-on field was one.
  const [searchOpen, setSearchOpen] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (searchOpen) field.current?.focus();
  }, [searchOpen]);

  // Debounced: a request per keystroke would hammer full-text search for
  // results nobody reads.
  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => onSearch(text.trim()), 250);
    return () => window.clearTimeout(timer.current);
  }, [text, onSearch]);

  async function refresh() {
    setPolling(true);
    try {
      const before = (await api.status()).last_pipeline_run_at;
      await api.poll();
      const deadline = Date.now() + 5 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 3000));
        const now = (await api.status()).last_pipeline_run_at;
        if (now && now !== before) {
          onRefreshed();
          break;
        }
      }
    } catch {
      /* the button settles either way; a failed poll is visible in the list */
    } finally {
      setPolling(false);
    }
  }

  return (
    <header className="app-header">
      {/* One header, not two. The redesign's whole claim is reclaimed vertical
          space, so an icon toolbar stacked under a text header would spend
          exactly what it set out to save -- and render Refresh, Search and
          dismiss twice each, with two accessible names apiece.

          The ids are the old row's, deliberately. Several specs drive
          `#poll-btn`, `#dismiss-all-btn` and `#digest-btn` directly, and those
          are the same three actions doing the same three jobs; renaming them
          would have churned the suite to no end. `.drawer-toggle` survives for
          the same reason -- it is the control other specs open the drawer by,
          restyled from a three-line icon to the two-bar one. */}
      <div className="header-row">
        <div className="header-title">
          <button className="drawer-toggle" aria-label="Open menu" onClick={onOpenDrawer}>
            <span /><span />
          </button>
          <span className="header-name">{title}</span>
          <span className="unread-count">{unread}</span>
        </div>

        <div className="header-actions">
          {canPoll && (
            <button
              id="poll-btn"
              className="header-action"
              disabled={polling}
              onClick={refresh}
            >
              {polling ? 'Refreshing…' : 'Refresh'}
            </button>
          )}
          <button
            id="dismiss-all-btn"
            className="header-action"
            onClick={onDismissAll}
          >
            Mark all read
          </button>
          <button
            id="digest-btn"
            className="header-action"
            onClick={onDigest}
          >
            What you missed
          </button>
          <button
            className="header-action is-ink search-toggle"
            aria-expanded={searchOpen}
            onClick={() => setSearchOpen((o) => !o)}
          >
            Search
          </button>
        </div>
      </div>

      {/* On a phone the field is behind the button above; on a desktop it is
          simply there. CSS decides, not a viewport read in JavaScript. */}
      <input
        ref={field}
        id="search"
        className={`search-input ${searchOpen ? 'open' : ''}`}
        type="search"
        placeholder="Filter articles…"
        autoComplete="off"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Escape' && !text) setSearchOpen(false); }}
      />
    </header>
  );
}

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
/** 24-box stroke icons, same family as the sidebar's `IconButton`. */
function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">
      <path fill="none" stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

const ICON = {
  refresh: 'M21 12a9 9 0 1 1-2.6-6.4 M21 3v6h-6',
  dismiss: 'm2 12 5 5L17 7 M22 7l-8.5 8.5',
  digest: 'M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Z'
        + ' M4 22a2 2 0 0 1-2-2v-9h4 M18 14h-8 M15 18h-5 M10 6h8v4h-8Z',
  search: 'm21 21-4.3-4.3 M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z',
};

export function Toolbar({
  search,
  onSearch,
  onDismissAll,
  onDigest,
  onRefreshed,
  canPoll,
}: {
  search: string;
  onSearch: (q: string) => void;
  onDismissAll: () => void;
  onDigest: () => void;
  onRefreshed: () => void;
  canPoll: boolean;
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
    <>
      {/* Icon plus label, and the phone hides the label. Three word-buttons and
          a field wrapped onto three rows there: 173px of a 664px screen, a
          quarter of the viewport spent before the first headline, with the
          search box crushed to 53px and reading "Fi". The label carries the
          accessible name on a desktop; `aria-label` carries it either way, so
          hiding the text never leaves a nameless button. */}
      {canPoll && (
        <button
          id="poll-btn"
          className={`btn-loadable btn-labelled ${polling ? 'is-loading' : ''}`}
          disabled={polling}
          onClick={refresh}
          aria-label="Refresh"
          title="Refresh — poll the feeds now"
        >
          <Icon d={ICON.refresh} />
          <span className="btn-label">Refresh</span>
        </button>
      )}
      <button
        id="dismiss-all-btn"
        className="btn-labelled"
        aria-label="Dismiss all"
        title="Mark every shown article as dealt with"
        onClick={onDismissAll}
      >
        <Icon d={ICON.dismiss} />
        <span className="btn-label">Dismiss all</span>
      </button>
      {/* The briefing, on request. It used to sit above the list and push the
          first article below the fold on every screen. */}
      <button
        id="digest-btn"
        className="btn-labelled"
        aria-label="What you missed"
        title="What you missed — a briefing over your unread articles"
        onClick={onDigest}
      >
        <Icon d={ICON.digest} />
        <span className="btn-label">What you missed</span>
      </button>

      {/* On a phone the field is behind this button; on a desktop the button is
          not rendered at all and the field is simply there. One markup, and the
          open state only ever means anything at phone width -- which is why it
          is CSS that decides, not a viewport read in JavaScript. */}
      <button
        className="search-toggle"
        aria-label="Search articles"
        aria-expanded={searchOpen}
        title="Search articles"
        onClick={() => setSearchOpen((o) => !o)}
      >
        <Icon d={ICON.search} />
      </button>
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

    </>
  );
}

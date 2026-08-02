import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

/**
 * Refresh, search and sort.
 *
 * Refresh is the interesting one: POST /poll returns immediately because the
 * work runs in a background thread, so the button would look inert for minutes.
 * It polls /status instead and only settles once last_pipeline_run_at advances,
 * which is what the server-rendered UI does.
 */
export function Toolbar({
  search,
  onSearch,
  sort,
  onSort,
  onDismissAll,
  onRefreshed,
  canPoll,
}: {
  search: string;
  onSearch: (q: string) => void;
  sort: 'date' | 'score';
  onSort: (s: 'date' | 'score') => void;
  onDismissAll: () => void;
  onRefreshed: () => void;
  canPoll: boolean;
}) {
  const [polling, setPolling] = useState(false);
  const [text, setText] = useState(search);
  const timer = useRef<number | undefined>(undefined);

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
      {canPoll && (
        <button
          id="poll-btn"
          className={`btn-loadable ${polling ? 'is-loading' : ''}`}
          disabled={polling}
          onClick={refresh}
        >
          <span className="btn-label">Refresh</span>
        </button>
      )}
      <button
        id="dismiss-all-btn"
        title="Mark every shown article as dealt with"
        onClick={onDismissAll}
      >
        Dismiss all
      </button>
      <input
        id="search"
        className="search-input"
        type="search"
        placeholder="Filter articles…"
        autoComplete="off"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="sort-toggle">
        <button className={sort === 'score' ? 'active' : ''} onClick={() => onSort('score')}>
          Score
        </button>
        <button className={sort === 'date' ? 'active' : ''} onClick={() => onSort('date')}>
          Date
        </button>
      </div>
    </>
  );
}

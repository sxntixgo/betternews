import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { Density } from '../density';

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
  density,
  onDensity,
  canPoll,
}: {
  search: string;
  onSearch: (q: string) => void;
  sort: 'date' | 'score';
  onSort: (s: 'date' | 'score') => void;
  onDismissAll: () => void;
  onRefreshed: () => void;
  density: Density;
  onDensity: (d: Density) => void;
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
      {/* Not palette-only. Measured: compact takes a phone card from 139px to
          101px, which is 4.79 stories on screen to 6.55. */}
      <button
        className="switch"
        role="switch"
        aria-checked={density === 'compact'}
        aria-label="Compact list"
        title="Compact list — hides summaries and tags"
        onClick={() => onDensity(density === 'compact' ? 'comfortable' : 'compact')}
      >
        <span className="switch-track"><span className="switch-knob" /></span>
        <span className="switch-label">Compact</span>
      </button>

      {/* One control with two states, not two buttons that happen to be
          adjacent. Date is the default and the left-hand position, so the knob
          resting at "off" means newest-first. */}
      <button
        className="switch"
        role="switch"
        aria-checked={sort === 'score'}
        aria-label="Sort by score instead of date"
        onClick={() => onSort(sort === 'score' ? 'date' : 'score')}
      >
        <span className="switch-label">Date</span>
        <span className="switch-track"><span className="switch-knob" /></span>
        <span className="switch-label">Score</span>
      </button>
    </>
  );
}

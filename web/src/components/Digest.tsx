import { useEffect, useState } from 'react';
import type { Digest as DigestData } from '@shared/api';
import { api } from '../api/client';
import { Modal } from './Modal';

/**
 * "What you missed" — one briefing over the unread set, on request.
 *
 * It used to sit above the reading list, which is the one place it could not
 * earn: it pushed the first article below the fold on every screen and was
 * several paragraphs of prose in the way of the list you came for. It is a
 * thing you read once, deliberately, so it is behind a button now.
 *
 * Cached server-side against a fingerprint of the unread set, so this is cheap
 * until that set changes. Dismissing clears the cache rather than hiding it
 * locally, which is why it comes back rebuilt rather than stale.
 */
export function Digest({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<DigestData | null>(null);
  const [failed, setFailed] = useState(false);

  // Fetched when opened, not on every page load. The briefing regenerates
  // whenever the unread set changes, so a request nobody asked to read is a
  // model call nobody asked for.
  useEffect(() => {
    api.digest().then(setData).catch(() => setFailed(true));
  }, []);

  return (
    <Modal onClose={onClose} ariaLabel="What you missed" className="digest-modal">
      <div className="digest-head">
        <strong>What you missed</strong>
        {data?.body && <span className="muted"> · {data.article_count} unread</span>}
        <div className="digest-actions">
          {/* Dismiss is not Close. Close leaves the briefing to be read again;
              dismiss tells the server to drop the cache and build a fresh one
              next time. Both end with the dialog shut, so they have to say
              which is which. */}
          {data?.body && (
            <button
              onClick={() => {
                api.dismissDigest().catch(() => {});
                onClose();
              }}
            >
              Dismiss
            </button>
          )}
          <button className="btn-icon" title="Close" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>
      </div>

      {/* Three states, and the empty one is not a failure: with nothing unread
          there is nothing to summarize, and a blank dialog reads as broken. */}
      {failed ? (
        <p className="muted">The briefing could not be loaded.</p>
      ) : !data ? (
        <p className="muted">Building your briefing…</p>
      ) : !data.body ? (
        <p className="muted">Nothing unread to summarize.</p>
      ) : (
        // Rendered as text, never as HTML: the body is model output over
        // attacker-supplied article titles.
        <div className="digest-body">
          {data.body.split('\n').map((line, i) => (
            <p key={i}>{line}</p>
          ))}
        </div>
      )}
    </Modal>
  );
}

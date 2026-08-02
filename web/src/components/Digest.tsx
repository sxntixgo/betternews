import { useEffect, useState } from 'react';
import type { Digest as DigestData } from '@shared/api';
import { api } from '../api/client';

/**
 * "What you missed" — one briefing over the unread set.
 *
 * Cached server-side against a fingerprint of that set, so this is cheap until
 * the set changes. Dismissing clears the cache rather than hiding it locally,
 * which is why it comes back rebuilt rather than stale.
 */
export function Digest() {
  const [data, setData] = useState<DigestData | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    api.digest().then(setData).catch(() => {});
  }, []);

  if (dismissed || !data?.body) return null;

  return (
    <div className="digest-card">
      <div className="digest-head">
        <strong>What you missed</strong>
        <span className="muted"> · {data.article_count} unread</span>
        <button
          className="btn-icon"
          title="Dismiss"
          onClick={() => {
            setDismissed(true);
            api.dismissDigest().catch(() => {});
          }}
        >
          ✕
        </button>
      </div>
      {/* Rendered as text, never as HTML: the body is model output over
          attacker-supplied article titles. */}
      <div className="digest-body">
        {data.body.split('\n').map((line, i) => (
          <p key={i}>{line}</p>
        ))}
      </div>
    </div>
  );
}

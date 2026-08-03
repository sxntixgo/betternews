import { useEffect, useState } from 'react';
import type { OllamaLog } from '@shared/api';
import { api } from '../api/client';
import { Modal } from '../components/Modal';

/**
 * What was actually sent to Ollama, and what came back.
 *
 * Off by default and bounded to the most recent 200: a busy pipeline would
 * otherwise fill the disk with prompts. Both sides of each call are shown --
 * the head is where a malformed prompt shows up, the tail is where a reasoning
 * model puts its answer.
 */
export function CallLog({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<OllamaLog | null>(null);
  const [failedOnly, setFailedOnly] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = (failed: boolean) =>
    api.ollamaLog(failed).then(setData).catch((e) => setError((e as Error).message));
  useEffect(() => { void load(failedOnly); }, [failedOnly]);

  const queue = data
    ? Object.entries(data.queue).map(([k, v]) => `${v} ${k}`).join(' · ')
    : '';

  return (
    <Modal onClose={onClose} ariaLabel="Ollama log" className="modal call-log">
      <nav className="modal-nav">
        <button className="btn-icon" onClick={onClose}>← Back</button>
        <strong>Ollama log</strong>
      </nav>
      <div className="modal-body">
        {error && <p className="error">{error}</p>}
        {!data ? <p className="loading">Loading…</p> : (
          <>
            <label className="settings-toggle">
              <input type="checkbox" checked={data.enabled}
                     onChange={async (e) => {
                       await api.setOllamaLog(e.target.checked);
                       await load(failedOnly);
                     }} />
              Record calls (keeps the most recent {data.keep})
            </label>

            <p className="muted">
              {data.summary.total} recorded, {data.summary.failed} failed.
              {/* An empty log means either no calls are being made or none
                  are needed. The queue is what tells them apart. */}
              {' '}Queue: {queue || 'empty'}.
              {data.last_run && ` Last run ${data.last_run.slice(0, 16).replace('T', ' ')}.`}
            </p>

            <div className="settings-actions">
              <label className="settings-toggle">
                <input type="checkbox" checked={failedOnly}
                       onChange={(e) => setFailedOnly(e.target.checked)} />
                Failures only
              </label>
              <button className="btn-secondary" onClick={async () => {
                if (!confirm('Clear the whole log?')) return;
                await api.clearOllamaLog();
                await load(failedOnly);
              }}>Clear</button>
            </div>

            {data.calls.length === 0 && (
              <p className="muted">
                {data.enabled ? 'Nothing recorded yet.' : 'Recording is off.'}
              </p>
            )}
            <table className="settings-table call-table">
              <tbody>
                {data.calls.map((c) => (
                  <tr key={c.id} className={c.ok ? '' : 'call-failed'}>
                    <td>
                      <button className="btn-icon call-summary"
                              onClick={() => setOpen(open === c.id ? null : c.id)}>
                        {(c.at ?? '').slice(11, 19)} · {c.action} · {c.model}
                        {' · '}{c.ok ? `${c.duration_ms}ms` : (c.error ?? `HTTP ${c.status_code}`)}
                      </button>
                      {open === c.id && (
                        <div className="call-detail">
                          <h4>Sent</h4>
                          <pre>{c.request_preview}</pre>
                          <h4>Received</h4>
                          <pre>{c.response_preview || '(nothing)'}</pre>
                          {c.error && <p className="feed-error">{c.error}</p>}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </Modal>
  );
}

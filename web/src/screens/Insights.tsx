import { useEffect, useState } from 'react';
import type { Insights as InsightsData } from '@shared/api';
import { api } from '../api/client';
import { BarChart } from '../components/BarChart';
import { Modal } from '../components/Modal';

/**
 * Is the ranking any good? Measured against your votes.
 *
 * One API call for all seven panels: they are only ever read together, and
 * seven round trips to draw one page would be the server's template layout
 * leaking into the client.
 */
export function Insights({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<InsightsData | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The field's own text, not the stored number: a controlled input that
  // reformatted mid-typing would fight the reader over "0.4" vs "0.40".
  const [draft, setDraft] = useState('');

  const load = () => api.insights()
    .then((d) => {
      setData(d);
      // Seed the field from whatever is in force, so "Set" without typing is a
      // no-op rather than a way to store NaN.
      setDraft(d.threshold.toFixed(2));
    })
    .catch((e) => setError((e as Error).message));
  useEffect(() => { void load(); }, []);

  // One path for every way of changing it, so the note, the error and the
  // reload cannot drift between the suggestion button and the manual one.
  const apply = async (value: number) => {
    setError(null);
    try {
      const { threshold } = await api.applyThreshold(value);
      setNote(`Threshold set to ${threshold}.`);
      await load();
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <Modal onClose={onClose} ariaLabel="Insights" className="modal insights-screen">
      <nav className="modal-nav">
        <button className="btn-icon" onClick={onClose}>← Back</button>
        <strong>Insights</strong>
      </nav>
      <div className="modal-body">
        {error && <p className="error">{error}</p>}
        {note && <p className="prefs-saved">{note}</p>}
        {!data ? <p className="loading">Loading…</p> : (
          <>
            {/* A run reporting 0 scored in ~0s is a failing run, not an idle
                one. This is the only place that says why. */}
            {data.llm_error && (
              <p className="feed-error">Last LLM error: {data.llm_error}</p>
            )}

            <h3>Scores</h3>
            <p className="muted">
              Where every scored article landed. The line is the current
              threshold, {data.threshold.toFixed(2)} — anything left of it is
              hidden.
            </p>
            <BarChart
              marker={data.threshold}
              bars={data.histogram.map((b) => ({
                label: b.lo.toFixed(2),
                value: b.n,
                title: `${b.lo.toFixed(2)}–${b.hi.toFixed(2)}: ${b.n} articles`,
              }))}
            />

            <h3>Agreement with your votes</h3>
            {data.agreement.rate === null ? (
              <p className="muted">Nothing voted on yet, so there is nothing to measure.</p>
            ) : (
              <p>
                <strong>{data.agreement.rate}%</strong> of your{' '}
                {data.agreement.votes} votes agreed with the score:{' '}
                {data.agreement.likes_ok} of {data.agreement.likes} likes scored
                above the threshold, {data.agreement.dislikes_ok} of{' '}
                {data.agreement.dislikes} dislikes below it.
              </p>
            )}
            {data.suggestion && (
              <div className="settings-actions">
                <span className="muted">
                  A threshold of {data.suggestion.threshold.toFixed(2)} would
                  agree {data.suggestion.rate}% of the time.
                </span>
                <button onClick={() => void apply(data.suggestion!.threshold)}>
                  Use it
                </button>
              </div>
            )}

            {/* Set it directly, reset it, or undo the last change. "Use it"
                above was the only way to move this number, which made a
                suggestion that hid everything a one-way door: the old value is
                overwritten, and a reader looking at an empty list has no
                control left to fix it with. */}
            <div className="settings-actions threshold-controls">
              <label htmlFor="threshold-input">Threshold</label>
              <input
                id="threshold-input"
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
              <button
                disabled={!Number.isFinite(parseFloat(draft))}
                onClick={() => void apply(parseFloat(draft))}
              >
                Set
              </button>
              <button
                disabled={data.threshold === data.threshold_default}
                onClick={() => void apply(data.threshold_default)}
              >
                Reset to default ({data.threshold_default.toFixed(2)})
              </button>
              {data.threshold_previous !== null
                && data.threshold_previous !== data.threshold && (
                <button onClick={() => void apply(data.threshold_previous!)}>
                  Undo — back to {data.threshold_previous.toFixed(2)}
                </button>
              )}
            </div>
            {/* The number alone does not tell you the list is about to empty.
                This is the state a reader actually got stuck in. */}
            {data.histogram.length > 0
              && data.histogram.every((b) => b.hi <= data.threshold || b.n === 0) && (
              <p className="feed-error">
                Every scored article is below this threshold, so the reading list
                will be empty. Lower it, then use “Rescore hidden”.
              </p>
            )}

            <h3>By feed</h3>
            <p className="muted">A feed you never like is a feed to drop.</p>
            <table className="settings-table">
              <tbody>
                {data.per_feed.map((f) => (
                  <tr key={f.feed}>
                    <td>{f.feed}</td>
                    <td className="muted">{f.articles} articles</td>
                    <td>👍 {f.likes} · 👎 {f.dislikes}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3>By topic</h3>
            <BarChart
              height={90}
              bars={data.per_topic.map((t) => ({
                label: t.topic, value: t.likes, secondary: t.dislikes,
                title: `${t.topic}: ${t.likes} liked, ${t.dislikes} disliked`,
              }))}
            />
            <p className="muted chart-legend">
              {data.per_topic.map((t) => t.topic).join(' · ')}
            </p>

            <h3>Pipeline</h3>
            <p>
              {data.pipeline.ready} ready · {data.pipeline.unscored} waiting to
              be scored · {data.pipeline.unsummarized} waiting to be
              summarized · {data.pipeline.hidden} hidden ·{' '}
              {data.pipeline.total} in total
            </p>

            <h3>Recent runs</h3>
            <table className="settings-table">
              <tbody>
                {data.runs.map((r) => (
                  <tr key={r.started_at ?? r.finished_at ?? Math.random()}>
                    <td>{(r.finished_at ?? r.started_at ?? '').slice(0, 16).replace('T', ' ')}</td>
                    <td className="muted">
                      {r.seconds === null ? '—' : `${r.seconds.toFixed(1)}s`}
                    </td>
                    <td>
                      {r.skipped ? 'skipped (already running)'
                        : `${r.scored_n} scored, ${r.summarized_n} summarized`}
                      {r.errors_n > 0 && <span className="feed-error"> · {r.errors_n} errors</span>}
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

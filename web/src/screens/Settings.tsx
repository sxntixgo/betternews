import { useEffect, useState } from 'react';
import type {
  ModelSettings, OllamaSettings, ReaderSettings, RetentionSettings, TopicRule,
} from '@shared/api';
import { api } from '../api/client';
import { Modal } from '../components/Modal';

/**
 * The settings panels.
 *
 * Admin-only end to end: the screen is only reachable from an admin's command
 * palette, and every endpoint behind it checks again. Hiding a control is not
 * a permission.
 */
export function Settings({ onClose }: { onClose: () => void }) {
  return (
    <Modal onClose={onClose} ariaLabel="Settings" className="modal settings-screen">
      <nav className="modal-nav">
        <button className="btn-icon" onClick={onClose}>← Back</button>
        <strong>Settings</strong>
      </nav>
      <div className="modal-body">
        <h3>Ollama</h3>
        <OllamaPanel />
        <h3>Models</h3>
        <ModelsPanel />
        <h3>Reading</h3>
        <ReaderPanel />
        <h3>Retention</h3>
        <RetentionPanel />
        <h3>Topic rules</h3>
        <TopicsPanel />
      </div>
    </Modal>
  );
}

function OllamaPanel() {
  const [state, setState] = useState<OllamaSettings | null>(null);
  const [host, setHost] = useState('');
  const [port, setPort] = useState('');
  const [probe, setProbe] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.ollamaSettings().then((s) => { setState(s); setHost(s.host); setPort(s.port); })
      .catch(() => {});
  }, []);
  if (!state) return <p className="loading">Loading…</p>;

  return (
    <div className="settings-panel">
      <p className="muted">
        {state.using_env
          ? `Blank, so the environment is used: ${state.env_base}`
          : `In use: ${state.active_base}`}
      </p>
      <div className="settings-row">
        <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="host" />
        <input value={port} onChange={(e) => setPort(e.target.value)} placeholder="port" />
      </div>
      {error && <p className="error">{error}</p>}
      {probe && <p className="prefs-saved">{probe}</p>}
      <div className="settings-actions">
        <button onClick={async () => {
          setError(null);
          try { setState(await api.saveOllama(host, port)); } catch (e) { setError((e as Error).message); }
        }}>Save</button>
        {/* Tests what is in the boxes, not what is stored: saving first and
            testing after is how a working setup gets replaced by a broken one. */}
        <button className="btn-secondary" onClick={async () => {
          setProbe('Testing…');
          const r = await api.testOllama(host, port);
          setProbe(r.message);
        }}>Test connection</button>
      </div>
    </div>
  );
}

function ModelsPanel() {
  const [state, setState] = useState<ModelSettings | null>(null);
  useEffect(() => { api.modelSettings().then(setState).catch(() => {}); }, []);
  if (!state) return <p className="loading">Loading…</p>;

  const unreachable = state.installed.length === 0;

  return (
    <div className="settings-panel">
      {unreachable && (
        <p className="error">
          Could not reach Ollama, so the installed models are unknown and no
          recommendation can be made. Check the connection above — a model
          configured here but not installed there fails silently on every call.
        </p>
      )}
      {/* The most load-bearing paragraph in Settings: it is the knowledge that
          stops someone picking a model that fails on every call, and it was
          dropped entirely when this panel was ported from the server UI. */}
      <p className="muted">
        Each job can use a different model, chosen from what your Ollama
        actually has. Recommendations weigh two things: whether the job needs
        structured JSON, and whether it runs on every article or only
        occasionally. <strong>Reasoning models</strong> (gpt-oss, deepseek-r1
        and similar) spend their output budget thinking before answering —
        fatal for the JSON jobs, expensive per article, and the best choice for
        the rare free-text ones.
      </p>

      <ul className="action-models">
        {state.actions.map((a) => (
          <li key={a.id} className={`action-model ${a.installed === false ? 'action-model-missing' : ''}`}>
            <div className="action-model-info">
              <strong>{a.label}</strong>
              {a.json_output && <span className="action-tag">JSON</span>}
              {a.heavy && <span className="action-tag">every article</span>}
              <p className="muted">{a.description}</p>
              <p className="muted action-guidance">{a.guidance}</p>
            </div>

            <select
              value={a.explicit}
              onChange={async (e) => setState(await api.saveModels({ [a.id]: e.target.value }))}
            >
              {/* Blank is a real choice, not a placeholder: it clears the
                  setting and lets the job fall back. Saying what it resolves
                  to is the difference between "set" and "defaulting". */}
              <option value="">Default{a.inherited ? ` (${a.current})` : ''}</option>
              {state.installed.map((m) => (
                <option key={m} value={m}>
                  {m}{m === a.recommended ? ' — recommended' : ''}
                </option>
              ))}
              {/* Kept in the list rather than silently swapped out, or the
                  panel would show a model the server is not using. */}
              {a.explicit && !state.installed.includes(a.explicit) && (
                <option value={a.explicit}>{a.explicit} — not installed</option>
              )}
            </select>

            {a.installed === false && (
              <p className="ollama-result ollama-result-bad">
                <strong>{a.current}</strong> is not installed on this Ollama
                server, so this job fails every time. Pick one of the models
                listed.
              </p>
            )}
            {a.suboptimal && (
              <p className="action-suggestion action-suggestion-warn">
                {a.current} reasons before answering, which suits this job
                poorly. {a.recommended && <>Try {a.recommended} — {a.why}</>}
              </p>
            )}
            {!a.suboptimal && a.recommended && a.recommended !== a.current && (
              <p className="action-suggestion">Suggested: {a.recommended} — {a.why}</p>
            )}
          </li>
        ))}
      </ul>

      <button className="btn-secondary" disabled={unreachable} onClick={async () => {
        await api.useRecommendedModels();
        setState(await api.modelSettings());
      }}>Apply every recommendation</button>
    </div>
  );
}


function ReaderPanel() {
  const [state, setState] = useState<ReaderSettings | null>(null);
  useEffect(() => { api.readerSettings().then(setState).catch(() => {}); }, []);
  if (!state) return <p className="loading">Loading…</p>;

  const save = async (patch: Partial<ReaderSettings>) =>
    setState(await api.saveReaderSettings(patch));

  return (
    <div className="settings-panel">
      <label className="settings-toggle">
        <input type="checkbox" checked={state.declickbait}
               onChange={(e) => save({ declickbait: e.target.checked })} />
        Rewrite clickbait headlines
      </label>
      <label className="settings-toggle">
        Article padding
        <select value={state.content_filter_mode}
                onChange={(e) => save({ content_filter_mode: e.target.value })}>
          {state.content_filter_modes.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </label>
      <label className="settings-toggle">
        <input type="checkbox" checked={state.content_filter_llm}
               onChange={(e) => save({ content_filter_llm: e.target.checked })} />
        Use the model to find padding as well as the regex
      </label>
      <label className="settings-toggle">
        <input type="checkbox" checked={state.notify_high_score}
               onChange={(e) => save({ notify_high_score: e.target.checked })} />
        Notify about high-scoring articles
      </label>
    </div>
  );
}

function RetentionPanel() {
  const [state, setState] = useState<RetentionSettings | null>(null);
  const [days, setDays] = useState('');
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.retentionSettings().then((s) => {
    setState(s);
    setDays(String(s.days));
  }).catch(() => {});
  useEffect(() => { void load(); }, []);
  if (!state) return <p className="loading">Loading…</p>;

  return (
    <div className="settings-panel">
      <p className="muted">
        {state.preview.articles} of {state.preview.total} articles are older than{' '}
        {state.days} days. {state.preview.saved} saved articles are never pruned.
      </p>
      <div className="settings-row">
        <input value={days} onChange={(e) => setDays(e.target.value)}
               type="number" min="0" />
        <button onClick={async () => {
          setError(null);
          try { setState(await api.saveRetention({ days: Number(days) })); }
          catch (e) { setError((e as Error).message); }
        }}>Save</button>
      </div>
      <label className="settings-toggle">
        <input type="checkbox" checked={state.confirmed}
               onChange={async (e) => setState(await api.saveRetention({ confirmed: e.target.checked }))} />
        {/* Ships inert on purpose: the default window is shorter than most
            existing corpora, so the first run would take nearly everything. */}
        I understand this deletes articles permanently
      </label>
      {error && <p className="error">{error}</p>}
      {note && <p className="prefs-saved">{note}</p>}
      <div className="settings-actions">
        <button
          disabled={!state.confirmed}
          onClick={async () => {
            if (!confirm(`Delete ${state.preview.articles} articles now?`)) return;
            setError(null);
            try {
              const { removed } = await api.pruneNow();
              setNote(`${removed} articles deleted.`);
              await load();
            } catch (e) { setError((e as Error).message); }
          }}
        >
          Prune now
        </button>
        <button className="btn-secondary" onClick={async () => {
          if (!confirm('Clear read articles for every reader?')) return;
          const { cleared } = await api.clearRead();
          setNote(`${cleared} cleared.`);
        }}>Clear read for everyone</button>
      </div>
    </div>
  );
}

function TopicsPanel() {
  const [topics, setTopics] = useState<TopicRule[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const load = () => api.topicRules().then((r) => setTopics(r.topics)).catch(() => {});
  useEffect(() => { void load(); }, []);

  return (
    <div className="settings-panel">
      <p className="muted">
        These apply to everyone. Your own preferences live on your profile.
      </p>
      {note && <p className="prefs-saved">{note}</p>}
      <table className="settings-table">
        <tbody>
          {topics.slice(0, 30).map((t) => (
            <tr key={t.topic}>
              <td>{t.topic}</td>
              <td className="muted">{t.articles}</td>
              <td>
                <button className={`btn-icon ${t.muted ? 'stance-on' : ''}`}
                        onClick={async () => { setTopics((await api.setTopicRule('mute', t.topic)).topics); }}>
                  Mute
                </button>
                <button className={`btn-icon ${t.adjustment > 0 ? 'stance-on' : ''}`}
                        onClick={async () => { setTopics((await api.setTopicRule('boost', t.topic, 0.1)).topics); }}>
                  Boost
                </button>
                <button className="btn-icon"
                        onClick={async () => { setTopics((await api.setTopicRule('clear', t.topic)).topics); }}>
                  Clear
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn-secondary" onClick={async () => {
        const { renormalized } = await api.tidyTopics();
        setNote(`${renormalized} articles re-tagged.`);
        void load();
      }}>Tidy existing topics</button>
    </div>
  );
}

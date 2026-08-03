import { useEffect, useState } from 'react';
import type { Me, Preferences, Topic, TokenSummary } from '@shared/api';
import { api } from '../api/client';
import { Modal } from '../components/Modal';

/**
 * The reader's own account: password, devices, topics and their profile.
 *
 * Everything here is scoped to the caller server-side, so this screen never
 * passes a user id — an id in a request is a wish, not a permission.
 */
export function Profile({ me, onClose }: { me: Me; onClose: () => void }) {
  return (
    <Modal onClose={onClose} ariaLabel="Your profile" className="modal profile-screen">
      <nav className="modal-nav">
        <button className="btn-icon" onClick={onClose}>← Back</button>
        <strong>{me.username}</strong>
      </nav>
      <div className="modal-body">
        <h3>What you like</h3>
        <PreferenceProfile />

        <h3>Topics</h3>
        <TopicStances />

        <h3>Devices</h3>
        <Tokens />

        <h3>Password</h3>
        <ChangePassword mustChange={false} />
      </div>
    </Modal>
  );
}

function PreferenceProfile() {
  const [data, setData] = useState<Preferences | null>(null);
  const [text, setText] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.preferences().then((p) => {
      setData(p);
      setText(p.profile_text);
    }).catch(() => {});
  }, []);

  if (!data) return <p className="loading">Loading…</p>;

  const boosted = Object.entries(data.stances).filter(([, v]) => v === 'more');
  const hidden = Object.entries(data.stances).filter(([, v]) => v === 'hide');

  return (
    <>
      {/* The evidence first: prose alone reads as vague however specific it is,
          because nothing says what produced it. */}
      <p className="prefs-evidence">
        Built from <strong>{data.liked}</strong> article{data.liked === 1 ? '' : 's'} you
        liked and <strong>{data.disliked}</strong> you disliked
        {boosted.length + hidden.length > 0 && ', plus the topics you chose'}.
      </p>
      {boosted.length + hidden.length > 0 && (
        <p className="topic-chips prefs-stances">
          {boosted.map(([t]) => <span className="topic-chip" key={t}>▲ {t}</span>)}
          {hidden.map(([t]) => <span className="topic-chip" key={t}>▼ {t}</span>)}
        </p>
      )}
      <textarea
        className="prefs-textarea"
        rows={8}
        value={text}
        onChange={(e) => { setText(e.target.value); setSaved(false); }}
      />
      <div className="prefs-actions">
        <button onClick={async () => { await api.savePreferences(text); setSaved(true); }}>
          Save
        </button>
        <button className="btn-secondary" onClick={() => api.regeneratePreferences()}>
          Regenerate
        </button>
        {saved && <span className="prefs-saved">Saved.</span>}
      </div>
    </>
  );
}

function TopicStances() {
  const [topics, setTopics] = useState<Topic[]>([]);
  useEffect(() => { api.topics().then((t) => setTopics(t.topics)).catch(() => {}); }, []);

  async function set(topic: string, stance: 'more' | 'hide' | null) {
    await api.setStance(topic, stance);
    setTopics((prev) => prev.map((t) => (t.topic === topic ? { ...t, stance } : t)));
  }

  return (
    <table className="topic-table">
      <tbody>
        {topics.slice(0, 25).map((t) => (
          <tr key={t.topic}>
            <td>{t.topic}</td>
            <td className="muted">{t.articles}</td>
            <td>
              <button className={`btn-icon ${t.stance === 'more' ? 'stance-on' : ''}`}
                      title="More of this" onClick={() => set(t.topic, 'more')}>▲</button>
              <button className={`btn-icon ${t.stance === 'hide' ? 'stance-on' : ''}`}
                      title="Hide this" onClick={() => set(t.topic, 'hide')}>▼</button>
              <button className="btn-icon" title="Neutral"
                      onClick={() => set(t.topic, null)}>✕</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Tokens() {
  const [tokens, setTokens] = useState<TokenSummary[]>([]);
  const [fresh, setFresh] = useState<string | null>(null);
  const [name, setName] = useState('');

  const load = () => api.tokens().then((t) => setTokens(t.tokens)).catch(() => {});
  useEffect(() => { void load(); }, []);

  return (
    <>
      <p className="muted">
        For apps that are not this browser — the phone, mostly. This browser uses
        a cookie and needs no token.
      </p>
      {fresh && (
        <div className="token-new">
          <p><strong>Copy this now — it is not shown again.</strong></p>
          <code className="token-value">{fresh}</code>
        </div>
      )}
      <table className="token-table">
        <tbody>
          {tokens.map((t) => (
            <tr key={t.id}>
              <td>{t.name}</td>
              <td className="muted">{t.last_used_at ? t.last_used_at.slice(0, 10) : 'never used'}</td>
              <td>
                <button className="btn-icon" onClick={async () => {
                  await api.revokeToken(t.id);
                  void load();
                }}>Revoke</button>
              </td>
            </tr>
          ))}
          {tokens.length === 0 && <tr><td className="muted">No devices yet.</td></tr>}
        </tbody>
      </table>
      <form
        className="token-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const made = await api.createToken(name.trim());
          setFresh(made.token);
          setName('');
          void load();
        }}
      >
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder="Device name, e.g. iPhone" maxLength={60} required />
        <button type="submit">Create token</button>
      </form>
    </>
  );
}

function ChangePassword({ mustChange }: { mustChange: boolean }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  return (
    <form
      className="password-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setMsg(null);
        try {
          await api.changePassword(current, next, confirm);
          setOk(true);
          setCurrent(''); setNext(''); setConfirm('');
        } catch (err) {
          setOk(false);
          setMsg((err as Error).message);
        }
      }}
    >
      {!mustChange && (
        <input type="password" value={current} autoComplete="current-password"
               onChange={(e) => setCurrent(e.target.value)}
               placeholder="Current password" required />
      )}
      <input type="password" value={next} autoComplete="new-password"
             onChange={(e) => setNext(e.target.value)}
             placeholder="New password" required />
      <input type="password" value={confirm} autoComplete="new-password"
             onChange={(e) => setConfirm(e.target.value)}
             placeholder="Confirm new password" required />
      {msg && <p className="error">{msg}</p>}
      {ok && <p className="prefs-saved">Password changed.</p>}
      <button type="submit">Change password</button>
    </form>
  );
}

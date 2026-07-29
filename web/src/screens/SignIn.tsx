import { useState } from 'react';
import { api, setToken } from '../api/client';

/**
 * Sign-in for the SPA is pasting a token, not a password.
 *
 * The API only accepts bearer tokens -- deliberately, so that a cookie riding
 * along on a cross-site request can never authenticate it. Tokens are created
 * in the server UI under Profile -> API tokens.
 */
export function SignIn({ onDone }: { onDone: () => void }) {
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setToken(value.trim());
    try {
      await api.me();          // prove it works before letting the app start
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="signin" onSubmit={submit}>
      <h1>Better News</h1>
      <p className="muted">
        Paste an API token. Create one in the server under{' '}
        <strong>Profile → API tokens</strong>.
      </p>
      <input
        type="password"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="bn_…"
        autoFocus
        required
      />
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy || !value.trim()}>
        {busy ? 'Checking…' : 'Continue'}
      </button>
    </form>
  );
}

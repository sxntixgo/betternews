import { useState } from 'react';
import { api } from '../api/client';

/**
 * Username and password.
 *
 * It used to ask for an API token, which is a developer's sign-in: you had to
 * visit the server UI, mint one, and paste it. The server sets a session cookie
 * now and this screen never handles a credential.
 */
export function SignIn({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api.login(username.trim(), password);
      if (me.must_change_password) {
        // An admin reset this password. The server UI blocks everything until
        // it changes; here there is nowhere to send them yet, so say so rather
        // than let them wonder why the server keeps asking.
        setError('Your password was reset — change it in the server UI.');
      }
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
      <input
        name="username"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        placeholder="Username"
        autoComplete="username"
        autoFocus
        required
      />
      <input
        name="password"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        autoComplete="current-password"
        required
      />
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy || !username.trim() || !password}>
        {busy ? 'Signing in…' : 'Sign in'}
      </button>
    </form>
  );
}

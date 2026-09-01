import { useState } from 'react';
import { isNetworkError } from '@shared/api';
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
      await api.login(username.trim(), password);
      // `must_change_password` is not handled here. The shell reads it from
      // /me and shows the change screen, which is a gate rather than a
      // message -- this used to point at a server UI that no longer exists.
      onDone();
    } catch (err) {
      // Never the engine's own words. WebKit rejects an unreachable server with
      // "Load failed", which this screen printed verbatim under a password
      // field -- so a certificate the phone did not trust read as a typo.
      setError(
        isNetworkError(err)
          ? 'Could not reach the server. Check your connection, then try again.'
          : (err as Error).message,
      );
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

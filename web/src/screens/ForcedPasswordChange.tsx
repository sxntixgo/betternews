import { useState } from 'react';
import { api } from '../api/client';

/**
 * The gate after an admin password reset.
 *
 * The server UI used to enforce this with an app-wide `before_request` that
 * redirected everything to the profile page. Once that UI is gone, this is the
 * only thing standing between a reset account and a reading list it should not
 * see yet -- so it is a full-screen block, not a dismissible banner.
 *
 * The server still refuses the change if the current password is wrong, and
 * still clears the flag itself; this does not decide anything, it only asks.
 */
export function ForcedPasswordChange({ username, onDone }: {
  username: string;
  onDone: () => void;
}) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.changePassword(current, next, confirm);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    /* Same skeleton as SignIn -- head, fields, pinned CTA -- because it shares
       `.signin` and the redesign hangs every style off those three blocks. It
       used to be bare inputs and buttons leaning on `.signin input`, which no
       longer exists; that left this screen with unstyled fields and unpinned
       buttons the moment sign-in was restyled.

       The labels are new. This form asked for three passwords using only
       placeholders, which vanish the moment you type -- on the one screen where
       telling "the password you were given" from "the new one" is the whole
       task. */
    <form className="signin forced-password" onSubmit={submit}>
      <div className="signin-head">
        <h1 className="signin-wordmark">Change your password</h1>
        <p className="signin-tagline">
          Signed in as {username}. An admin reset this password, so it has to
          change before you can read anything.
        </p>
      </div>

      <div className="signin-fields">
        <label className="field">
          <span className="field-label">Current password</span>
          <input type="password" value={current} autoComplete="current-password"
                 onChange={(e) => setCurrent(e.target.value)}
                 placeholder="The password you were given" required />
        </label>
        <label className="field">
          <span className="field-label">New password</span>
          <input type="password" value={next} autoComplete="new-password"
                 onChange={(e) => setNext(e.target.value)} required />
        </label>
        <label className="field">
          <span className="field-label">Confirm new password</span>
          <input type="password" value={confirm} autoComplete="new-password"
                 onChange={(e) => setConfirm(e.target.value)} required />
        </label>
        {error && <p className="error field-error">{error}</p>}
      </div>

      <div className="signin-cta">
        <button type="submit" disabled={busy}>
          {busy ? 'Changing…' : 'Change password'}
        </button>
        {/* A way out that is not "read anyway": someone given the wrong
            temporary password would otherwise be stuck here with no exit. */}
        <button type="button" className="btn-secondary"
                onClick={() => void api.logout().finally(onDone)}>
          Sign out
        </button>
      </div>
    </form>
  );
}

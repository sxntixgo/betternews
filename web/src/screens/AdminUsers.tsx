import { useEffect, useState } from 'react';
import type { AdminUserList } from '@shared/api';
import { api } from '../api/client';
import { Modal } from '../components/Modal';

/**
 * The user table.
 *
 * Two rules the server enforces and this mirrors: the last admin cannot be
 * demoted or deleted, and you cannot delete yourself. Both come back as a 409
 * with a readable message, so the screen shows the server's words rather than
 * guessing at the reason.
 */
export function AdminUsers({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<AdminUserList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [temp, setTemp] = useState<{ username: string; password: string } | null>(null);

  const load = () => api.adminUsers().then(setData).catch((e) => setError((e as Error).message));
  useEffect(() => { void load(); }, []);

  async function run(fn: () => Promise<AdminUserList>) {
    setError(null);
    try {
      setData(await fn());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Modal onClose={onClose} ariaLabel="Users" className="modal admin-users">
      <nav className="modal-nav">
        <button className="btn-icon" onClick={onClose}>← Back</button>
        <strong>Users</strong>
      </nav>
      <div className="modal-body">
        {error && <p className="error">{error}</p>}
        {/* Shown once and stored nowhere else, exactly like the HTML page. */}
        {temp && (
          <p className="prefs-saved">
            Temporary password for {temp.username}: <code>{temp.password}</code>
            {' '}— they must change it at next sign-in. It is not shown again.
          </p>
        )}
        {!data ? <p className="loading">Loading…</p> : (
          <table className="settings-table">
            <tbody>
              {data.users.map((u) => (
                <tr key={u.id}>
                  <td>
                    <div className="feed-title">
                      {u.username}{u.id === data.me && <span className="muted"> — you</span>}
                    </div>
                    <div className="muted">
                      {u.votes} votes · {u.read_count} read
                      {u.last_login_at && ` · last in ${u.last_login_at.slice(0, 10)}`}
                    </div>
                    {u.must_change_password && (
                      <div className="muted">must change password at next sign-in</div>
                    )}
                  </td>
                  <td>
                    <select
                      value={u.role}
                      onChange={(e) => void run(() =>
                        api.setUserRole(u.id, e.target.value as 'user' | 'admin'))}
                    >
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td>
                    <button className="btn-icon" onClick={async () => {
                      setError(null);
                      try {
                        setTemp(await api.resetUserPassword(u.id));
                        await load();
                      } catch (e) { setError((e as Error).message); }
                    }}>
                      Reset password
                    </button>
                    {/* Not offered on your own row. The server refuses it
                        anyway; this is about not showing a dead control. */}
                    {u.id !== data.me && (
                      <button className="btn-icon" onClick={() => {
                        if (confirm(`Delete ${u.username}? Their votes and read state go too.`)) {
                          void run(() => api.deleteUser(u.id));
                        }
                      }}>
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Modal>
  );
}

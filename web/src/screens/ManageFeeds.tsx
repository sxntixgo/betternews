import { useEffect, useState } from 'react';
import type { FolderWithCount, ManagedFeed } from '@shared/api';
import { api } from '../api/client';
import { downloadBlob } from '../download';
import { Modal } from '../components/Modal';

/**
 * Adding, pausing, filing, tagging and deleting feeds, plus OPML and the
 * folders feeds are filed in.
 *
 * Every mutation here is admin-only server-side. The screen is still readable
 * by anyone — seeing that a feed is failing is not a privilege — but the
 * controls are hidden for a plain reader, because a button that 403s reads as
 * breakage rather than as a permission.
 */
export function ManageFeeds({ isAdmin, onClose }: { isAdmin: boolean; onClose: () => void }) {
  const [feeds, setFeeds] = useState<ManagedFeed[]>([]);
  const [folders, setFolders] = useState<FolderWithCount[]>([]);
  const [url, setUrl] = useState('');
  const [newFolder, setNewFolder] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = () => Promise.all([
    api.manageFeeds().then((r) => setFeeds(r.feeds)),
    api.folders().then((r) => setFolders(r.folders)),
  ]).catch(() => {});
  const folderName = (id: number | null) => folders.find((d) => d.id === id)?.name ?? '';
  useEffect(() => { void load(); }, []);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Modal onClose={onClose} ariaLabel="Feeds" className="modal manage-feeds">
      <nav className="modal-nav">
        <button className="btn-icon" onClick={onClose}>← Back</button>
        <strong>Feeds</strong>
      </nav>

      <div className="modal-body">
        {error && <p className="error">{error}</p>}
        {note && <p className="prefs-saved">{note}</p>}

        {isAdmin && (
          <form
            className="feed-add"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await api.addFeed(url.trim());
                setUrl('');
              });
            }}
          >
            <input value={url} onChange={(e) => setUrl(e.target.value)}
                   placeholder="https://example.com/feed.xml" required />
            <button type="submit">Add feed</button>
          </form>
        )}

        {/* Folders are the reader's own groups for the sidebar. Each feed is
            in at most one; deleting a folder leaves its feeds, unfiled. */}
        <h3>Folders</h3>
        <ul className="folder-list">
          {folders.map((d) => (
            <li key={d.id}>
              {isAdmin ? (
                <input
                  aria-label={`Folder name: ${d.name}`}
                  defaultValue={d.name}
                  onBlur={(e) => {
                    const name = e.target.value.trim();
                    if (name && name !== d.name) void run(() => api.renameFolder(d.id, name));
                    else e.target.value = d.name;
                  }}
                />
              ) : (
                <span>{d.name}</span>
              )}
              <span className="muted">{d.feeds} feed{d.feeds === 1 ? '' : 's'}</span>
              {isAdmin && (
                <button
                  className="btn-icon"
                  aria-label={`Delete folder ${d.name}`}
                  onClick={() => {
                    if (confirm(`Delete the folder ${d.name}? Its feeds stay, just not in a folder.`)) {
                      void run(() => api.deleteFolder(d.id));
                    }
                  }}
                >
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
        {isAdmin && (
          <form
            className="folder-add"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await api.createFolder(newFolder.trim());
                setNewFolder('');
              });
            }}
          >
            <input value={newFolder} onChange={(e) => setNewFolder(e.target.value)}
                   aria-label="New folder" placeholder="New folder" required />
            <button type="submit">Add folder</button>
          </form>
        )}

        <h3>Feeds</h3>
        <table className="feed-table">
          <tbody>
            {feeds.map((f) => (
              <tr key={f.id} className={f.paused ? 'paused' : ''}>
                <td>
                  <div className="feed-title">{f.title ?? f.url}</div>
                  <div className="muted feed-url">{f.url}</div>
                  {/* The reason a 43-day outage went unnoticed was that
                      nothing showed this. */}
                  {f.last_error && (
                    <div className="feed-error">
                      {f.consecutive_failures}× — {f.last_error}
                    </div>
                  )}
                </td>
                <td>
                  {isAdmin ? (
                    <select
                      className="feed-folder"
                      aria-label={`Folder for ${f.title ?? f.url}`}
                      value={f.folder_id ?? ''}
                      onChange={(e) => void run(() => api.setFeedFolder(
                        f.id, e.target.value === '' ? null : Number(e.target.value)))}
                    >
                      <option value="">No folder</option>
                      {folders.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                    </select>
                  ) : (
                    <span className="muted">{folderName(f.folder_id)}</span>
                  )}
                </td>
                <td>
                  {isAdmin ? (
                    <input
                      className="feed-tags"
                      defaultValue={f.tags.join(', ')}
                      placeholder="tags"
                      onBlur={(e) => void run(() => api.setFeedTags(f.id, e.target.value))}
                    />
                  ) : (
                    <span className="muted">{f.tags.join(', ')}</span>
                  )}
                </td>
                <td>
                  {isAdmin && (
                    <input
                      className="feed-threshold"
                      type="number" min="0" max="1" step="0.05"
                      defaultValue={f.score_threshold ?? ''}
                      placeholder="default"
                      title="Score threshold for this feed; blank uses the global one"
                      onBlur={(e) => void run(() =>
                        api.setFeedThreshold(f.id, e.target.value === '' ? null : Number(e.target.value)))}
                    />
                  )}
                </td>
                <td className="feed-actions">
                  {isAdmin && (
                    <>
                      <button className="btn-icon" onClick={() => void run(() =>
                        f.paused ? api.resumeFeed(f.id) : api.pauseFeed(f.id))}>
                        {f.paused ? 'Resume' : 'Pause'}
                      </button>
                      <button
                        className="btn-icon"
                        onClick={() => {
                          // Deleting a feed takes its articles with it, and
                          // nothing brings them back.
                          if (confirm(`Delete ${f.title ?? f.url} and its articles?`)) {
                            void run(() => api.deleteFeed(f.id));
                          }
                        }}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3>OPML</h3>
        <div className="opml-actions">
          <button onClick={() => void run(async () => {
            const { blob, filename } = await api.exportOpml();
            downloadBlob(blob, filename);
          })}>
            Export
          </button>
          {isAdmin && (
            <label className="btn-secondary opml-import">
              Import
              <input
                type="file"
                accept=".opml,.xml,text/xml"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  void run(async () => {
                    const { added } = await api.importOpml(file);
                    setNote(`${added} feed${added === 1 ? '' : 's'} added.`);
                  });
                  e.target.value = '';
                }}
              />
            </label>
          )}
        </div>
      </div>
    </Modal>
  );
}

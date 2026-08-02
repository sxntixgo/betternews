import { SHORTCUTS } from '../keyboard';

/**
 * The shortcut list, on `?`.
 *
 * The server-rendered UI has had five keyboard shortcuts for months with
 * nothing announcing them, which makes them features only their author knows
 * about. Borrowed from job-application-tracker, where the palette and this
 * overlay are why its shortcuts get used.
 */
export function ShortcutsOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="shortcuts-overlay" onClick={(e) => e.stopPropagation()}>
        <h2>Keyboard shortcuts</h2>
        <table>
          <tbody>
            {SHORTCUTS.map((s) => (
              <tr key={s.keys}>
                <td>
                  <kbd>{s.keys}</kbd>
                </td>
                <td>{s.does}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">Esc to close</p>
      </div>
    </div>
  );
}

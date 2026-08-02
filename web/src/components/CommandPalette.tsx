import { useEffect, useMemo, useRef, useState } from 'react';

export interface Command {
  id: string;
  label: string;
  run: () => void;
}

/**
 * Ctrl/⌘ K.
 *
 * The point is not speed for the author — it is that every action has a name a
 * reader can find by typing part of it, instead of hunting the sidebar. It is
 * also the cheapest way to make a feature discoverable without adding a button
 * to a toolbar that is already full.
 */
export function CommandPalette({
  commands,
  onClose,
}: {
  commands: Command[];
  onClose: () => void;
}) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => input.current?.focus(), []);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.label.toLowerCase().includes(q));
  }, [commands, query]);

  // Reset the highlight when the list changes under it, or Enter runs whatever
  // happens to sit at a stale index.
  useEffect(() => setActive(0), [query]);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, matches.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = matches[active];
      if (cmd) {
        cmd.run();
        onClose();
      }
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="command-palette" onClick={(e) => e.stopPropagation()}>
        <input
          ref={input}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a command…"
          aria-label="Command"
        />
        <ul>
          {matches.map((c, i) => (
            <li key={c.id}>
              <button
                className={`command-item ${i === active ? 'active' : ''}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => {
                  c.run();
                  onClose();
                }}
              >
                {c.label}
              </button>
            </li>
          ))}
          {matches.length === 0 && <li className="muted">Nothing matches.</li>}
        </ul>
      </div>
    </div>
  );
}

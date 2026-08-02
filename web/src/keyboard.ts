/**
 * True when the event came from somewhere the reader is typing.
 *
 * Without this, searching for "jklo" scrolls the list and likes things. It is
 * the guard every global shortcut needs, and the reason to have one place that
 * decides rather than a repeated check per handler.
 */
export function isEditableTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return (
    el.tagName === 'INPUT' ||
    el.tagName === 'TEXTAREA' ||
    el.tagName === 'SELECT' ||
    el.isContentEditable
  );
}

/**
 * What `?` shows.
 *
 * One list, so the overlay cannot drift from the handlers — a shortcuts sheet
 * that lies is worse than none.
 */
export const SHORTCUTS: { keys: string; does: string }[] = [
  { keys: 'j', does: 'Next article' },
  { keys: 'k', does: 'Previous article' },
  { keys: 'l', does: 'Like the focused article' },
  { keys: 's', does: 'Save it for later' },
  { keys: 'o', does: 'Open it in a new tab' },
  { keys: 'r', does: 'Read it here' },
  { keys: '/', does: 'Jump to search' },
  { keys: 'Ctrl/⌘ K', does: 'Command palette' },
  { keys: '?', does: 'This list' },
  { keys: 'Esc', does: 'Close whatever is open' },
];

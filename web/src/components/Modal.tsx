import { useEffect, useRef } from 'react';

/**
 * The one modal.
 *
 * Nine screens hand-rolled `<div className="modal-backdrop" onClick={onClose}>`
 * and not one of them had a role, `aria-modal`, a focus trap or focus
 * restoration. The server-rendered reader they replaced was a native
 * `<dialog aria-modal="true">`, which gave all four for free — so moving to the
 * SPA was an accessibility regression, and this is the repair.
 *
 * Modelled on `job-application-tracker`'s `Modal.tsx`, with one deliberate
 * difference: Escape does not `stopPropagation`. The shell listens for Escape
 * to close the command palette and the reader, and swallowing it here meant a
 * modal opened from the palette left the palette behind it open.
 */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), ' +
  'select:not([disabled]), textarea:not([disabled]), ' +
  '[tabindex]:not([tabindex="-1"])';

/**
 * Matching the selector is not the same as being focusable.
 *
 * The OPML import is a hidden `<input type="file">` inside a styled label —
 * `display: none`, so it matches `input:not([disabled])` and can never hold
 * focus. It sorted last in the feeds dialog, so `activeElement === last` was
 * never true, the wrap never fired, and Tab walked straight out into the
 * article list behind. Anything without a layout box is not in the tab order.
 */
function focusableIn(el: HTMLElement): HTMLElement[] {
  return Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter((n) => n.offsetWidth > 0 || n.offsetHeight > 0 || n.getClientRects().length > 0);
}

export function Modal({ onClose, ariaLabel, className, children }: {
  onClose: () => void;
  ariaLabel: string;
  className?: string;
  children: React.ReactNode;
}) {
  const container = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<Element | null>(null);

  useEffect(() => {
    restoreTo.current = document.activeElement;
    const el = container.current;
    if (!el) return;
    // The first control, or the container itself when there is none — a modal
    // with nothing focusable still has to take focus off the page behind it.
    (focusableIn(el)[0] ?? el).focus();

    return () => {
      // Back to whatever opened it, so a keyboard user is not dumped at the
      // top of the document every time they close something.
      const prev = restoreTo.current;
      if (prev instanceof HTMLElement) prev.focus();
    };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const el = container.current;
      if (!el) return;
      const focusable = focusableIn(el);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      // Wrap at both ends. Without this, Tab walks out of the modal and into
      // the article list behind it, which is still scrollable and clickable.
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        ref={container}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        className={className}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

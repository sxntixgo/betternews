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
      // Move focus ourselves on every Tab, rather than only wrapping at the
      // two ends. The boundary version assumed the browser's own tab order
      // matches `focusableIn()` and that focus always lands on one of those
      // elements -- true in Chromium, false in WebKit, where Tab skips buttons
      // and links by default (macOS Full Keyboard Access) and parks focus on
      // <body> instead. `activeElement === last` was then never true, the wrap
      // never fired, and Tab walked out of the dialog into the article list
      // behind it. Safari is a browser this app is actually read in.
      //
      // Driving it directly costs nothing in Chromium -- same order, same wrap
      // -- and stops the trap depending on a behaviour that varies by engine
      // and by an OS accessibility setting.
      e.preventDefault();
      const idx = focusable.indexOf(document.activeElement as HTMLElement);
      // -1 means focus is somewhere we do not manage (<body>, or the dialog
      // container itself on open). Enter the list from whichever end the
      // reader is heading towards.
      const next = e.shiftKey
        ? (idx <= 0 ? focusable.length - 1 : idx - 1)
        : (idx === -1 || idx === focusable.length - 1 ? 0 : idx + 1);
      focusable[next].focus();
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

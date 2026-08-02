import { useEffect } from 'react';

/**
 * Swipe right to like, swipe left to dismiss.
 *
 * Only attached on a coarse pointer: on a laptop these listeners would fight
 * text selection for no benefit.
 *
 * Vertical wins over horizontal at the first movement, so scrolling the list
 * never starts a swipe. That check has to happen once, on the first move, and
 * be remembered — deciding per event makes a diagonal scroll flicker between
 * the two.
 */
export function useSwipe(
  onLike: (id: number) => void,
  onDismiss: (id: number) => void,
  enabled = true,
) {
  useEffect(() => {
    if (!enabled) return;
    if (!('ontouchstart' in window) && !window.matchMedia('(pointer: coarse)').matches) {
      return;
    }

    let row: HTMLElement | null = null;
    let x0 = 0;
    let y0 = 0;
    let dragging = false;
    let decided = false;

    const reset = () => {
      if (row) {
        row.style.transition = 'transform 0.2s ease';
        row.style.transform = '';
        const el = row;
        window.setTimeout(() => {
          el.style.transition = '';
        }, 220);
      }
      row = null;
      dragging = false;
      decided = false;
    };

    function onStart(e: TouchEvent) {
      const target = e.target as HTMLElement;
      // Let the buttons and links inside a card do their own job.
      if (target.closest('button, a')) return;
      row = target.closest('.article-row');
      if (!row) return;
      x0 = e.touches[0].clientX;
      y0 = e.touches[0].clientY;
      dragging = false;
      decided = false;
    }

    function onMove(e: TouchEvent) {
      if (!row) return;
      const dx = e.touches[0].clientX - x0;
      const dy = e.touches[0].clientY - y0;
      if (!decided) {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
        decided = true;
        if (Math.abs(dy) > Math.abs(dx)) {
          row = null;          // a scroll, not a swipe
          return;
        }
        dragging = true;
      }
      if (!dragging) return;
      row.style.transform = `translateX(${dx}px)`;
      const ratio = Math.abs(dx) / row.offsetWidth;
      row.classList.toggle('swipe-like-active', dx > 0 && ratio > 0.4);
      row.classList.toggle('swipe-dismiss-active', dx < 0 && ratio > 0.4);
    }

    function onEnd(e: TouchEvent) {
      if (!row || !dragging) {
        reset();
        return;
      }
      const dx = e.changedTouches[0].clientX - x0;
      const ratio = Math.abs(dx) / row.offsetWidth;
      const id = Number(row.dataset.articleId ?? row.id.replace('card-', ''));
      row.classList.remove('swipe-like-active', 'swipe-dismiss-active');
      if (ratio > 0.4 && id) {
        if (navigator.vibrate) navigator.vibrate(10);
        if (dx > 0) onLike(id);
        else onDismiss(id);
      }
      reset();
    }

    document.addEventListener('touchstart', onStart, { passive: true });
    document.addEventListener('touchmove', onMove, { passive: true });
    document.addEventListener('touchend', onEnd, { passive: true });
    document.addEventListener('touchcancel', reset, { passive: true });
    return () => {
      document.removeEventListener('touchstart', onStart);
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onEnd);
      document.removeEventListener('touchcancel', reset);
    };
  }, [onLike, onDismiss, enabled]);
}

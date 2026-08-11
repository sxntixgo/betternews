/**
 * Whether the reading list shows photos.
 *
 * A third display preference beside `theme` and `density`, and per-device for
 * the same reason: the right answer differs between a phone on a metered
 * connection and a desktop on wifi.
 *
 * It is not the same lever as `density`. Compact drops the summary and the
 * tags, which are text the model produced; this drops the images, which are
 * the only thing on a card fetched from a third party. Turning them off makes
 * the list denser *and* stops every card reaching out to a news site's CDN --
 * two reasons a reader might want it, and neither is served by the other
 * toggle.
 *
 * Stored in localStorage beside `theme`, `sidebar-collapsed` and `density`: a
 * non-secret display preference, and the sanctioned use of that store.
 */
export type Photos = 'on' | 'off';

const KEY = 'photos';

export function loadPhotos(): Photos {
  try {
    return localStorage.getItem(KEY) === 'off' ? 'off' : 'on';
  } catch {
    return 'on';
  }
}

export function setPhotos(value: Photos): void {
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* private mode: the toggle still works, it just forgets */
  }
}

/** Stamped on <html>, so it is one attribute rather than a prop threaded
 *  through every component that renders an image. */
export function applyPhotos(value: Photos): void {
  document.documentElement.dataset.photos = value;
}

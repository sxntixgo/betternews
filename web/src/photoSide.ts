/**
 * Which side of the card the photo sits on.
 *
 * A display preference beside `photos`, and per-device like it. Defaults to
 * **right**, which is where the redesign put it; left is the older layout some
 * readers scan faster, the eye landing on the picture before the headline.
 *
 * Only the float changes side. The text still wraps the photo and reclaims the
 * full width below it either way, so nothing else about the card moves.
 *
 * Stored in localStorage beside `photos`, `density` and `tags`: a non-secret
 * display preference, and the sanctioned use of that store.
 */
export type PhotoSide = 'left' | 'right';

const KEY = 'photo-side';

export function loadPhotoSide(): PhotoSide {
  try {
    return localStorage.getItem(KEY) === 'left' ? 'left' : 'right';
  } catch {
    return 'right';
  }
}

export function setPhotoSide(value: PhotoSide): void {
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* private mode: the choice still works, it just forgets */
  }
}

/** Stamped on <html>, so it is one attribute rather than a prop threaded
 *  through every component that renders a card. */
export function applyPhotoSide(value: PhotoSide): void {
  document.documentElement.dataset.photoSide = value;
}

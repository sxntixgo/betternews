/**
 * Whether the reading list shows the topic tag.
 *
 * A fourth display preference beside `theme`, `density` and `photos`, and
 * per-device for the same reason they are.
 *
 * It replaces a breakpoint rather than adding to one. The tag was desktop-only
 * -- `display: none` at base, `inline` only inside the 900px block -- because
 * the meta line is a single line on a phone and the tag is the item that would
 * wrap it. That made it the one thing on the card a reader could not choose,
 * and a switch in the drawer that did nothing on a phone would have been worse
 * than no switch.
 *
 * Defaults to **off**, which is what a phone shows today: the switch then means
 * the same thing on both devices, and a desktop reader turns it on once. The
 * phone's single meta line is protected by the 13ch cap in `App.css`, not by
 * hiding the control.
 *
 * Stored in localStorage beside `theme`, `density`, `photos` and
 * `sidebar-collapsed`: a non-secret display preference, and the sanctioned use
 * of that store.
 */
export type Tags = 'on' | 'off';

const KEY = 'tags';

export function loadTags(): Tags {
  try {
    return localStorage.getItem(KEY) === 'on' ? 'on' : 'off';
  } catch {
    return 'off';
  }
}

export function setTags(value: Tags): void {
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* private mode: the toggle still works, it just forgets */
  }
}

/** Stamped on <html>, so it is one attribute rather than a prop threaded
 *  through every component that renders part of a card. */
export function applyTags(value: Tags): void {
  document.documentElement.dataset.tags = value;
}

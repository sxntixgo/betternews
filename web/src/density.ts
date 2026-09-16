/**
 * How much of each story the list shows.
 *
 * Measured on a 664px phone viewport, which is what motivated this:
 *
 *     comfortable   139px per card   4.79 on screen
 *     compact       101px per card   6.55 on screen
 *
 * The interesting part is what compact drops and what it does not. It drops
 * the summary -- that is the whole 38px -- and the hidden-reason line on the
 * Hidden list, which is a second paragraph doing the same job there. It does
 * **not** drop the tag, and no longer can: the tag sits on the meta line beside
 * the action buttons, whose 40px tap target sets that row's height either way,
 * so hiding it saved nothing vertically and cost a reader a control. That is
 * the `tags` switch's business now, and it is one lever per reason.
 *
 * `kind` stays in either mode. It is one short word from a closed vocabulary
 * and it is the single most useful thing on the card for judging why something
 * scored the way it did -- a fixture listing and a transfer story are the same
 * subject and opposite value.
 *
 * Stored in localStorage beside `theme` and `sidebar-collapsed`: a non-secret
 * display preference, and per-device on purpose, since the right answer differs
 * between a phone and a desktop.
 */
export type Density = 'comfortable' | 'compact';

const KEY = 'density';

export function loadDensity(): Density {
  try {
    return localStorage.getItem(KEY) === 'compact' ? 'compact' : 'comfortable';
  } catch {
    return 'comfortable';
  }
}

export function setDensity(value: Density): void {
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* private mode: the toggle still works, it just forgets */
  }
}

/** Stamped on <html>, so it is one attribute rather than a prop threaded
 *  through every component that renders part of a card. */
export function applyDensity(value: Density): void {
  document.documentElement.dataset.density = value;
}

/**
 * Light / dark / system.
 *
 * `theme` in localStorage is the one sanctioned exception to keeping nothing
 * there: a non-secret UI preference with no auth implications. Everything about
 * who you are lives in an HttpOnly cookie instead.
 *
 * A two-way toggle cannot express "follow the OS", which is why this is a
 * preference of three rather than a boolean.
 */
export type ThemePreference = 'light' | 'dark' | 'system';

const KEY = 'theme';

function systemPrefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

/** Resolve the preference and stamp it on <html data-theme>. */
export function applyTheme(pref: ThemePreference): void {
  const effective = pref === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : pref;
  document.documentElement.dataset.theme = effective;
}

export function loadTheme(): ThemePreference {
  // Guarded like `density`, `photos` and `tags`, and this one mattered most:
  // `App.tsx` calls it from a `useState` initializer, so where localStorage
  // throws -- Safari private browsing, a browser set to block site data -- the
  // throw came out of render and the app put nothing on the screen at all.
  try {
    const stored = localStorage.getItem(KEY);
    return stored === 'light' || stored === 'dark' ? stored : 'system';
  } catch {
    return 'system';
  }
}

export function setTheme(pref: ThemePreference): void {
  try {
    // 'system' is the default, so storing it would add a key that means
    // nothing. Removing keeps localStorage empty for anyone who never chose.
    if (pref === 'system') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, pref);
  } catch {
    /* private mode: the theme still applies, it just forgets */
  }
  // Outside the guard: applying the theme is the part the reader can see, and
  // it does not depend on the store having accepted anything.
  applyTheme(pref);
}

/**
 * Follow the OS while the preference is 'system'.
 * Returns the unsubscribe, so a caller can drop it on unmount.
 */
export function watchSystemTheme(getPref: () => ThemePreference): () => void {
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  const onChange = () => {
    if (getPref() === 'system') applyTheme('system');
  };
  mq.addEventListener('change', onChange);
  return () => mq.removeEventListener('change', onChange);
}

/**
 * Installability and the offline signal.
 *
 * The Flask app shipped a manifest and a service worker and was installable on
 * a phone home screen; the SPA shipped neither, which left two pieces of code
 * that looked alive and were not. `favicon.ts` calls `navigator.setAppBadge()`,
 * which is a no-op outside an installed PWA, and `App.css` styles an
 * `.offline-bar` that nothing ever showed.
 */

/**
 * Registers the shell cache. Production only.
 *
 * A worker on the dev server caches module URLs Vite is actively rewriting, so
 * it fights HMR and serves stale code — and Playwright reuses a developer's own
 * dev server, which would install it on their machine as a side effect of
 * running the tests.
 */
export function registerServiceWorker(): void {
  if (!import.meta.env.PROD) return;
  if (!('serviceWorker' in navigator)) return;
  // After load, not during: registration competes with the first render for
  // the network otherwise, and the shell is only needed on the *next* visit.
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js').catch(() => {
      /* http on a non-localhost origin, or storage denied: the app still works */
    });
  });
}

/**
 * Calls back with the current connectivity, now and on every change.
 *
 * `navigator.onLine` is famously weak — it reports whether there is *a*
 * network, not whether this server is reachable — so it is used only to hide
 * the bar, never to block a request. A request that fails while `onLine` is
 * true still surfaces its own error.
 */
export function watchConnectivity(onChange: (online: boolean) => void): () => void {
  const update = () => onChange(navigator.onLine);
  window.addEventListener('online', update);
  window.addEventListener('offline', update);
  update();
  return () => {
    window.removeEventListener('online', update);
    window.removeEventListener('offline', update);
  };
}

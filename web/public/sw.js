// The app shell, cached so a cold start with no network shows the reader
// instead of the browser's error page.
//
// Deliberately *only* the shell. Caching article bodies is a bigger feature
// than it looks -- it needs a local store and a write queue for votes cast
// offline, or the reader silently loses them -- and it is still deferred (D2 in
// the plan). What this buys is that the app opens, says it is offline, and
// stops looking broken.
//
// The version is in the cache name: bump it and the old cache is dropped on
// activate. Without that a stale shell survives every deploy, which is exactly
// the "I deployed and nothing changed" failure the old worker caused.
// Bumped to v2 deliberately: activate drops every cache that is not this
// name, which is the only way to clear the poisoned '/' entry v1 left on
// devices that had already signed in. Bump it whenever this file's caching
// behaviour changes, not merely when the app does.
const VERSION = 'shell-v2';

// Paths Caddy routes to Flask, not to the SPA. The worker must not touch them.
// /api was already excluded; the rest were not, and that was the bug: a
// navigation to /login is a *successful* navigation, so its response -- the
// server-rendered login page -- was being stored under the key '/'. Any later
// navigation that failed then served Flask's login HTML as the app shell, and
// that page has no #root and loads no bundle. A blank app, persisting until
// storage was cleared.
const SERVER_PATHS = /^\/(api|login|register|logout|health|static)(\/|$)/;

// The built asset filenames are hashed, so they cannot be listed here. They are
// cached as they are requested instead; only the entry point is known upfront.
const PRECACHE = ['/', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(VERSION)
      // addAll is atomic -- one 404 and nothing is cached. Fetch individually so
      // a missing icon cannot leave the app with no shell at all.
      .then((c) => Promise.all(PRECACHE.map((u) => c.add(u).catch(() => {}))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (e) => {
  const { request } = e;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never cached, and never served from cache. A reading list out of cache
  // would show articles as unread that were read on another device, a cached
  // 401 would lock someone out until they cleared storage, and a cached login
  // page would masquerade as the app shell.
  if (SERVER_PATHS.test(url.pathname)) return;

  // A navigation always tries the network first: the shell changes on deploy
  // and a cache-first navigation is how a stale build sticks around. Falling
  // back to the cached shell is what makes offline work.
  if (request.mode === 'navigate') {
    e.respondWith(
      fetch(request)
        .then((res) => {
          // Only an HTML 200 is the shell. A redirect to /login, or anything
          // the server returns for a path this worker should not have seen,
          // must never end up under the key '/'.
          const html = res.ok
            && (res.headers.get('content-type') || '').includes('text/html');
          if (html) {
            const copy = res.clone();
            caches.open(VERSION).then((c) => c.put('/', copy));
          }
          return res;
        })
        .catch(() => caches.match('/').then((r) => r ?? Response.error())),
    );
    return;
  }

  // Hashed assets: cache-first is safe because the filename changes when the
  // content does.
  e.respondWith(
    caches.match(request).then((hit) => hit ?? fetch(request).then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(VERSION).then((c) => c.put(request, copy));
      }
      return res;
    })),
  );
});

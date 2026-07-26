// Service worker: keep already-read-able articles readable without a network.
//
// The reader is used mostly on a phone over Tailscale, so "no connectivity"
// is a normal state rather than an edge case. Article bodies are cached as
// they're opened and served cache-first, because a summarized article does not
// change — refetching it buys nothing.
//
// Votes made offline are queued and replayed on reconnect. Nothing else is
// queued: replaying a stale dismiss-all after an hour offline would be worse
// than losing it.

const VERSION = 'v2';
const SHELL = `shell-${VERSION}`;
const ARTICLES = `articles-${VERSION}`;

const PRECACHE = [
  '/',
  '/static/style.css',
  '/static/manifest.json',
  'https://unpkg.com/htmx.org@1.9.12',
];

// Article bodies never change once summarized.
const ARTICLE_RE = /\/article\/\d+\/content$/;
const VOTE_RE = /\/vote\/\d+\/(1|-1)$/;

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(SHELL)
      .then(c => c.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== SHELL && k !== ARTICLES).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

async function cacheFirst(request) {
  const cache = await caches.open(ARTICLES);
  const hit = await cache.match(request);
  if (hit) {
    // Refresh in the background; the reader gets the cached copy immediately.
    fetch(request).then(r => { if (r.ok) cache.put(request, r.clone()); }).catch(() => {});
    return hit;
  }
  const fresh = await fetch(request);
  if (fresh.ok) cache.put(request, fresh.clone());
  return fresh;
}

async function networkFirst(request) {
  try {
    return await fetch(request);
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw err;
  }
}

// ── offline vote queue ────────────────────────────────────────────────────────

const DB_NAME = 'betterread-outbox';

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore('votes', { autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function withStore(mode, fn) {
  return openDB().then(db => new Promise((resolve, reject) => {
    const tx = db.transaction('votes', mode);
    const out = fn(tx.objectStore('votes'));
    tx.oncomplete = () => resolve(out.result !== undefined ? out.result : out);
    tx.onerror = () => reject(tx.error);
  }));
}

const queueVote = url => withStore('readwrite', s => s.add({ url, at: Date.now() }));
const readVotes = () => withStore('readonly', s => s.getAll());
const clearVotes = () => withStore('readwrite', s => s.clear());

async function flushVotes() {
  let queued = [];
  try { queued = await readVotes(); } catch (e) { return; }
  if (!queued.length) return;
  for (const item of queued) {
    try {
      await fetch(item.url, { method: 'POST', headers: { 'HX-Request': 'true' } });
    } catch (e) {
      return;   // still offline; keep the queue for next time
    }
  }
  await clearVotes();
  const clients = await self.clients.matchAll();
  clients.forEach(c => c.postMessage({ type: 'votes-flushed', count: queued.length }));
}

self.addEventListener('message', e => {
  if (e.data && e.data.type === 'flush-votes') e.waitUntil(flushVotes());
});

self.addEventListener('fetch', e => {
  const { request } = e;
  const url = new URL(request.url);

  if (request.method === 'POST' && VOTE_RE.test(url.pathname)) {
    e.respondWith(
      fetch(request.clone()).catch(async () => {
        await queueVote(url.pathname);
        // 202: the vote is recorded locally and will be replayed.
        return new Response('', { status: 202 });
      })
    );
    return;
  }

  if (request.method !== 'GET') return;

  if (ARTICLE_RE.test(url.pathname)) {
    e.respondWith(cacheFirst(request));
    return;
  }

  if (url.pathname.startsWith('/static/') || url.origin !== self.location.origin) {
    e.respondWith(
      caches.match(request).then(hit => hit || fetch(request).then(r => {
        if (r.ok) caches.open(SHELL).then(c => c.put(request, r.clone()));
        return r;
      }))
    );
    return;
  }

  e.respondWith(networkFirst(request));
});

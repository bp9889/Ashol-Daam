/* Asol Dam's service worker: makes the site installable as an app and usable offline.
   - Pages, styles and scripts: always fetched fresh when online (so updates show at once);
     the last copy is kept for when you're offline.
   - Your checked products (/api/products…): the same, so offline you can still open them.
   - Everything else in /api (checking a new link, alerts…) needs the internet and isn't cached.
   - Fonts and the animation library from other sites: served from the cache, refreshed in the background. */
const VERSION = "asol-dam-v4";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== VERSION) await caches.delete(key);
    await self.clients.claim();
  })());
});

const savedCopy = (request) => caches.open(VERSION).then((c) => c.match(request, { ignoreSearch: request.mode !== "navigate" && !request.url.includes("/api/") }));

// A saved copy, marked so the page can say "no connection, showing what was saved".
async function marked(copy) {
  const headers = new Headers(copy.headers);
  headers.set("X-Asol-Saved", "1");
  return new Response(await copy.blob(), { status: copy.status, statusText: copy.statusText, headers });
}

// Whenever your list arrives, quietly keep a copy of each product on it (only the ones not kept
// yet), so every product in "Recently checked" opens offline, not just the ones you clicked.
async function keepListedProducts(listResponse) {
  try {
    const list = await listResponse.json();
    const cache = await caches.open(VERSION);
    for (const p of list.slice(0, 40)) {
      const key = new Request(`/api/products/${p.id}`);
      if (await cache.match(key)) continue;
      const response = await fetch(`/api/products/${p.id}?refresh=false`);
      if (response.ok) await cache.put(key, response);
    }
  } catch (err) { /* offline or busy: try again next time */ }
}

async function freshFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const copy = response.clone();  // clone now: the page is about to read the original
      caches.open(VERSION).then((c) => c.put(request, copy));
      if (new URL(request.url).pathname === "/api/products") keepListedProducts(response.clone());
    }
    return response;
  } catch (err) {
    const copy = await savedCopy(request);
    if (copy) return new URL(request.url).pathname.startsWith("/api/") ? marked(copy) : copy;
    if (request.mode === "navigate") {  // offline and never saved: the home page still opens
      const home = await caches.open(VERSION).then((c) => c.match("/", { ignoreSearch: true }));
      if (home) return home;
    }
    throw err;
  }
}

async function savedFirst(request) {
  const cache = await caches.open(VERSION);
  const copy = await cache.match(request);
  const update = fetch(request).then((response) => {
    if (response.ok || response.type === "opaque") cache.put(request, response.clone());
    return response;
  }).catch(() => copy);
  return copy || update;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin === location.origin) {
    if (url.pathname.startsWith("/api/") && !/^\/api\/products(\/\d+)?$/.test(url.pathname)) return;
    event.respondWith(freshFirst(request));
  } else if (/fonts\.(googleapis|gstatic)\.com|cdnjs\.cloudflare\.com/.test(url.hostname)) {
    event.respondWith(savedFirst(request));
  }
});

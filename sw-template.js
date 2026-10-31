/*
 * RESQ SOS service worker.
 * vite.config.ts copies this file to dist/sw.js at build time and fills in
 * the version (a hash of every built file) and the list of files to cache.
 * Any change to the app therefore changes the cache name automatically.
 */
const VERSION = "__VERSION__";
const CACHE_PREFIX = "resq-sos-";
const CACHE = CACHE_PREFIX + VERSION;
const PRECACHE = __PRECACHE__;

const SCOPE = self.registration.scope; // e.g. https://host/  or  https://host/app/
const INDEX_URL = new URL("./", SCOPE).href;

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      // addAll is all-or-nothing: if any file fails, install fails and the old worker stays.
      await cache.addAll(
        PRECACHE.map((path) => new Request(new URL(path, SCOPE).href, { cache: "reload" })),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE)
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (!url.href.startsWith(SCOPE)) return;
  event.respondWith(respond(request, event));
});

// A response that came through a redirect cannot be used to answer a page load.
function clean(response) {
  if (!response.redirected) return response;
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

// The saved copy can disappear (storage cleared, or evicted by the browser).
// Re-save everything on the next page load that has internet. Harmless when offline.
function rebuild(cache) {
  return cache
    .addAll(PRECACHE.map((path) => new Request(new URL(path, SCOPE).href, { cache: "reload" })))
    .catch(() => {});
}

async function respond(request, event) {
  const cache = await caches.open(CACHE);
  if (request.mode === "navigate") {
    const page = await cache.match(INDEX_URL, { ignoreSearch: true, ignoreVary: true });
    if (page) return clean(page);
    event.waitUntil(rebuild(cache));
  } else {
    const hit = await cache.match(request, { ignoreSearch: true, ignoreVary: true });
    if (hit) return hit;
  }
  try {
    return await fetch(request);
  } catch {
    return new Response(
      "RESQ SOS is not saved on this phone yet, and there is no internet.\n" +
        "If you need help now: call 112, or text your emergency and location to the RESQ number.\n" +
        "To use the SOS page offline, open it once with internet.",
      {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      },
    );
  }
}

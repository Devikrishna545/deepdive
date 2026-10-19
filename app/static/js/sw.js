// DeepDive service worker: makes the app installable and keeps the app shell (styles, scripts,
// icons) available offline. Research data (/api) is never cached: reports must always be live.
const CACHE = "deepdive-shell-v1";
const SHELL = ["/static/css/app.css", "/static/js/common.js", "/static/js/index.js", "/static/js/run.js",
  "/static/icons/sprite.svg", "/static/icons/app-icon.svg", "/static/manifest.webmanifest"];

self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api")) return;
  if (url.pathname.startsWith("/static/")) {
    // Network first so a new deploy shows at once; the cache covers offline.
    e.respondWith(fetch(e.request).then((resp) => {
      const copy = resp.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
      return resp;
    }).catch(() => caches.match(e.request)));
  }
});

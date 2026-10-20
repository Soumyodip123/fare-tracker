const SHELL = "fares-shell-v1";
self.addEventListener("install", e => e.waitUntil(caches.open(SHELL).then(c => c.addAll(["./", "./index.html", "./manifest.webmanifest"]))));
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const sameOrigin = new URL(e.request.url).origin === location.origin;
  e.respondWith(fetch(e.request).then(r => {                       // network first: always prefer fresh fares
    if (sameOrigin) { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request)));
});

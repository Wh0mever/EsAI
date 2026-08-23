/* EsAI Service Worker — app-shell caching, offline fallback.
 * Strategy:
 *   - navigations (HTML): network-first, fall back to cached page, then /offline.html
 *   - static assets (/_next/static, images, fonts, icons): cache-first (stale-while-revalidate)
 *   - /api/* (incl. streaming chat): always network, never cached
 * Bump CACHE_VERSION to invalidate old caches on deploy.
 */
// v5: сброс кэшей после починки статики. У части пользователей в SHELL_CACHE
// лежала страница от старой сборки, чей css уже удалён с сервера, — она
// открывалась без стилей. Смена версии разом выбрасывает такие копии.
const CACHE_VERSION = "esai-v5";
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const OFFLINE_URL = "/offline.html";

// Minimal app-shell precache. Keep this tiny so install never fails.
const PRECACHE = [
  OFFLINE_URL,
  "/esai-logo.svg",
  "/esai-mark.svg",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      // addAll is atomic; use individual puts so one 404 doesn't abort install.
      await Promise.all(
        PRECACHE.map(async (url) => {
          try {
            const res = await fetch(url, { cache: "no-cache" });
            if (res && res.ok) await cache.put(url, res.clone());
          } catch (_) {
            /* ignore individual precache misses */
          }
        })
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((k) => !k.startsWith(CACHE_VERSION))
          .map((k) => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

function isStaticAsset(url) {
  if (url.pathname.startsWith("/_next/static/")) return true;
  if (url.pathname.startsWith("/_next/image")) return true;
  return /\.(?:js|css|woff2?|ttf|otf|eot|png|jpe?g|gif|webp|avif|svg|ico)$/i.test(
    url.pathname
  );
}

self.addEventListener("fetch", (event) => {
  const req = event.request;

  // Only handle GET; let the browser deal with POST/PUT/etc. (chat is POST -> untouched).
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Same-origin only.
  if (url.origin !== self.location.origin) return;

  // Never intercept API / auth / SSE traffic.
  if (url.pathname.startsWith("/api/")) return;

  // Navigations: network-first, fall back to cache, then offline page.
  const isNavigation =
    req.mode === "navigate" ||
    (req.headers.get("accept") || "").includes("text/html");

  if (isNavigation) {
    event.respondWith(
      (async () => {
        try {
          const fresh = await fetch(req);
          // Cache a copy of successful navigations for offline reuse.
          if (fresh && fresh.ok) {
            const cache = await caches.open(SHELL_CACHE);
            cache.put(req, fresh.clone()).catch(() => {});
          }
          return fresh;
        } catch (_) {
          const cached = await caches.match(req);
          if (cached) return cached;
          const offline = await caches.match(OFFLINE_URL);
          return (
            offline ||
            new Response("Offline", { status: 503, statusText: "Offline" })
          );
        }
      })()
    );
    return;
  }

  // Static assets: cache-first with background refresh (stale-while-revalidate).
  if (isStaticAsset(url)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(STATIC_CACHE);
        const cached = await cache.match(req);
        const network = fetch(req)
          .then((res) => {
            if (res && res.ok) cache.put(req, res.clone()).catch(() => {});
            return res;
          })
          .catch(() => null);
        return cached || (await network) || new Response("", { status: 504 });
      })()
    );
    return;
  }

  // Everything else: pass through (network), no caching.
});

// Allow the page to trigger an immediate activation after an update.
self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

/* ---------- Web Push ---------- */

// Push received: show a notification. Payload is JSON when the backend sends
// structured data; fall back to plain text / defaults so nothing is silent.
self.addEventListener("push", (event) => {
  let d = {};
  try {
    d = event.data.json();
  } catch (e) {
    d = { title: "EsAI", body: event.data && event.data.text ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(d.title || "EsAI", {
      body: d.body || "",
      icon: d.icon || "/icon-192.png",
      badge: d.badge || "/icon-192.png",
      tag: d.tag || "esai",
      data: { url: d.url || "/" },
    })
  );
});

// Notification click: focus an existing window (navigating it to the target
// URL) or open a new one.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if ("focus" in c) {
          c.navigate && c.navigate(url);
          return c.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});

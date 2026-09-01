/// <reference lib="webworker" />

/**
 * Lemely's service worker.
 *
 * D5.15 moved this build from `vite-plugin-pwa`'s **generateSW** strategy to
 * **injectManifest** for one reason: generateSW emits a worker with no `push`
 * listener at all, so D5.10's payload-less push had nowhere to land and the
 * backend could send a notification that nothing on the client would ever
 * render. The alternative — `workbox.importScripts` of a hand-written file in
 * `public/` — was rejected because `public/` is copied verbatim and is
 * invisible to `tsc -b`, oxlint and vitest.
 *
 * **Everything below the push handler is the generateSW behaviour written out
 * by hand.** Moving strategies means the precache setup is ours now, so it has
 * to be reproduced deliberately or it is silently lost. In particular the
 * `/^\/api/` navigation denylist is load-bearing and carries forward the
 * original config's reasoning: student and teacher marks, grades and
 * review-queue data are live and must never be served from a cache.
 *
 * The interesting logic is deliberately *not* here — it is in
 * `lib/push/pushDecision.ts`, which vitest can drive. This file is the adapter
 * that wires real events to it.
 */

import { clientsClaim } from "workbox-core"
import { precacheAndRoute, createHandlerBoundToURL } from "workbox-precaching"
import { NavigationRoute, registerRoute } from "workbox-routing"

import {
  CLIENT_REPLY_TIMEOUT_MS,
  DEFAULT_PUSH_URL,
  GENERIC_PUSH_BODY,
  GENERIC_PUSH_TITLE,
  PUSH_CONTENT_REQUEST,
  decidePushNotification,
  pickClientToFocus,
  type PushNotificationContent,
} from "@/lib/push/pushDecision"

declare const self: ServiceWorkerGlobalScope

// --- App shell (the generateSW half, reproduced) ----------------------------

// Precaching is production-only, because it is the one cache no server-side
// setting can reach. A precaching worker answers navigations out of Cache
// Storage before the request ever leaves the browser, so neither a Cloudflare
// Cache Rule nor Development Mode gets a say — staging would keep serving the
// previous deploy's shell to anyone who had loaded it before. staging exists to
// show the newest deploy immediately, so it does not precache.
//
// Gated on the production hostnames rather than naming staging, so preview
// deploys and `localhost` stay live too; the only host that precaches is the
// one real users are on.
const PRECACHE_HOSTS = new Set(["lemelyig.com", "www.lemelyig.com"])
const precacheEnabled = PRECACHE_HOSTS.has(self.location.hostname)

// `self.__WB_MANIFEST` is replaced at build time with the precache manifest
// built from `injectManifest.globPatterns` in vite.config.ts. Read it
// unconditionally: vite-plugin-pwa substitutes that literal token wherever it
// appears, and keeping it out of the branch means the build-time injection does
// not depend on this runtime guard.
const precacheManifest = self.__WB_MANIFEST

if (precacheEnabled) {
  precacheAndRoute(precacheManifest)

  // `navigateFallback: "/index.html"` with `navigateFallbackDenylist: [/^\/api/]`.
  // The SPA serves every navigation from the precached shell — except anything
  // under /api, which must reach the network.
  registerRoute(
    new NavigationRoute(createHandlerBoundToURL("/index.html"), {
      denylist: [/^\/api/],
    }),
  )
} else {
  // Registering no fetch handler at all is what makes every request pass
  // straight to the network. But a worker installed back when this host did
  // precache still holds that shell in Cache Storage, and it would go on being
  // served until something evicted it — so drop every cache on activate. This
  // is what actually gets a returning staging visitor onto the new deploy
  // rather than the one they saw last time.
  self.addEventListener("activate", (event) => {
    event.waitUntil(
      caches
        .keys()
        .then((keys) => Promise.all(keys.map((key) => caches.delete(key))))
        .then(() => undefined),
    )
  })
}

// `registerType: "autoUpdate"` meant the new worker took over without asking.
// Preserved explicitly, because injectManifest does not imply it.
self.skipWaiting().catch(() => {
  // A browser that refuses the skip simply activates on the next navigation;
  // nothing here is worth failing the install over.
})
clientsClaim()

// --- Push (the reason this file exists) -------------------------------------

/**
 * Ask an open page what just arrived.
 *
 * The worker cannot make the authenticated request itself — the bearer token
 * lives in `localStorage`, which a `ServiceWorkerGlobalScope` has no access to
 * (D5.15 §2). Mirroring the token somewhere the worker *could* read was
 * rejected: a second, longer-lived copy of a credential that every logout and
 * device eviction would then also have to clear is exactly the session-boundary
 * erosion P5.7/D5.12 exists to prevent. So the page does the fetch and the
 * credential never leaves the page context.
 *
 * Resolves null when nothing answers in time, which is the normal state with
 * the app closed rather than an error.
 */
async function requestContentFromClients(): Promise<unknown> {
  const clients = await self.clients.matchAll({
    type: "window",
    includeUncontrolled: true,
  })
  if (clients.length === 0) return null

  return await new Promise<unknown>((resolve) => {
    let settled = false
    const finish = (value: unknown): void => {
      if (settled) return
      settled = true
      resolve(value)
    }

    // A page that never answers must not hold the push event open; the event's
    // lifetime is bounded by the browser anyway, and a prompt honest fallback
    // beats a slow real answer.
    const timer = self.setTimeout(() => {
      finish(null)
    }, CLIENT_REPLY_TIMEOUT_MS)

    const channel = new MessageChannel()
    channel.port1.onmessage = (event: MessageEvent) => {
      self.clearTimeout(timer)
      finish(event.data)
    }

    // Only the first answer is used, so asking every page costs nothing and
    // avoids guessing which one is able to reply.
    for (const client of clients) {
      client.postMessage({ type: PUSH_CONTENT_REQUEST }, [channel.port2])
    }
  })
}

/**
 * Show something, always.
 *
 * The try/catch spans the decision as well as the fetch, not just the fetch.
 * Browsers require *some* notification per push, and the penalty for an
 * exception escaping here is not a missing notification but the engine's own
 * "This site has been updated in the background" — strictly worse than our
 * generic one, because it tells the reader nothing and looks like a bug. So the
 * guarantee is enforced at the one place the requirement actually applies,
 * rather than by making the pure decision function defend against inputs a
 * structured clone cannot produce.
 */
async function handlePush(): Promise<void> {
  let content: PushNotificationContent = {
    title: GENERIC_PUSH_TITLE,
    body: GENERIC_PUSH_BODY,
    url: DEFAULT_PUSH_URL,
  }

  try {
    // Any failure to reach a page is just an absent reply, which
    // `decidePushNotification` already renders as the generic notification.
    content = decidePushNotification(await requestContentFromClients())
  } catch {
    // Keep the generic content initialised above.
  }

  await self.registration.showNotification(content.title, {
    body: content.body,
    icon: "/pwa-192x192.png",
    badge: "/pwa-192x192.png",
    data: { url: content.url },
  })
}

self.addEventListener("push", (event: PushEvent) => {
  // `waitUntil` is mandatory rather than tidy: browsers require *some*
  // notification per push, and several show their own "This site has been
  // updated in the background" message if the handler resolves without one.
  // `handlePush` cannot reject, so the generic notification is always reached.
  event.waitUntil(handlePush())
})

self.addEventListener("notificationclick", (event: NotificationEvent) => {
  event.notification.close()

  const data: unknown = event.notification.data
  const target =
    typeof data === "object" && data !== null && typeof (data as { url?: unknown }).url === "string"
      ? (data as { url: string }).url
      : "/"

  event.waitUntil(
    (async () => {
      const clients = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      })
      const existing = pickClientToFocus(clients)
      if (existing !== null) {
        await existing.focus()
        // Navigating an existing page keeps the reader's session and app state
        // instead of booting a second copy of the SPA.
        await existing.navigate(target).catch(() => {
          // Some engines refuse cross-document navigation from a worker; the
          // focus above already put the reader in the right window.
        })
        return
      }
      await self.clients.openWindow(target)
    })(),
  )
})

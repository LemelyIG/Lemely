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
import { SHARE_CACHE, handleShareTargetFetch } from "@/sw/shareTarget"
import { fetchWidgetDataOrStub } from "@/sw/widgetBridge"

/*
 * The PWA Widgets API (Windows 11 Widgets Board / Android home-screen
 * widgets) is Chromium-experimental and not yet in TypeScript's own
 * `lib.webworker.d.ts` — same situation `vite-env.d.ts` documents for the
 * File Handling API's `LaunchParams`. Declared narrow, to exactly what this
 * file calls: `getByInstanceId`, `matchAll`, `updateByInstanceId`,
 * `widgetuninstall` and `periodicsync`-driven updates are real parts of the
 * API this app does not use.
 *
 * Augmenting `ServiceWorkerGlobalScopeEventMap` (rather than typing the
 * listener's `event` parameter by hand at each call site) is what lets
 * `self.addEventListener("widgetinstall", ...)` below infer `WidgetEvent`
 * through the same generic overload `"push"`/`"message"` already use, so a
 * typo'd event name or a wrong property on `event.widget` is still a
 * `tsc -b` error, not a runtime one.
 */
interface WidgetDefinition {
  tag: string
  /** camelCased from the manifest's `ms_ac_template` at the browser level —
   * the Adaptive Card template's URL. */
  msAcTemplate: string
  /** camelCased from the manifest's `data` — a URL the browser expects to
   * return JSON, per the spec, not the JSON payload itself. */
  data: string
}

interface WidgetObject {
  definition: WidgetDefinition
}

interface WidgetsNamespace {
  getByTag(tag: string): Promise<WidgetObject | undefined>
  updateByTag(tag: string, payload: { template: string; data: string }): Promise<void>
}

interface WidgetEvent extends ExtendableEvent {
  widget: WidgetObject
}

declare global {
  interface ServiceWorkerGlobalScopeEventMap {
    widgetinstall: WidgetEvent
    widgetresume: WidgetEvent
  }
}

declare const self: ServiceWorkerGlobalScope & { widgets: WidgetsNamespace }

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
  // under /api, which must reach the network, and now /share-target (below):
  // a precached-shell navigation response would out-race the redirect the
  // share-target handler itself returns.
  registerRoute(
    new NavigationRoute(createHandlerBoundToURL("/index.html"), {
      denylist: [/^\/api/, /^\/share-target/],
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
        // A6 review fix (addendum L4): was every key. `SHARE_CACHE` holds a
        // share-target/file-handler stash that may be sitting between the OS
        // delivering a file and `CorrectPaper.tsx` reading it on mount — a
        // worker update activating in that window must not discard it out
        // from under the reader.
        .then((keys) => Promise.all(keys.filter((key) => key !== SHARE_CACHE).map((key) => caches.delete(key))))
        .then(() => undefined),
    )
  })
}

// Packet A7 (`silent-update-swap`): `registerType` is now `"prompt"`, not
// `"autoUpdate"`, and a new worker must stay in `waiting` — not take over —
// until the reader clicks "Reload" on `<UpdateToast>` (`useServiceWorkerUpdate`).
// An unconditional call at install time defeated that regardless of the
// page-side gate: it advanced this worker straight past `waiting` on every
// install, so `wb.addEventListener("waiting", ...)` (vite-plugin-pwa's own
// `registerSW.ts`) never even fired. Skipping now happens only on request,
// via the `SKIP_WAITING` message `updateServiceWorker(true)` sends.
self.addEventListener("message", (event: ExtendableMessageEvent) => {
  if ((event.data as { type?: unknown } | undefined)?.type === "SKIP_WAITING") {
    self.skipWaiting().catch(() => {
      // A browser that refuses the skip simply activates on the next
      // navigation; nothing here is worth failing the message handler over.
    })
  }
})
clientsClaim()

// --- Web Share Target (manifest's `share_target`) ---------------------------

// File-scope and unconditional — registered regardless of `precacheEnabled`,
// because the OS share sheet reaches this worker on staging and localhost
// too, not only on the production hosts precaching is scoped to. Workbox's
// `registerRoute` only ever matches navigations (GET); the share sheet POSTs
// to `/share-target`, which needs its own listener.
self.addEventListener("fetch", (event: FetchEvent) => {
  const url = new URL(event.request.url)
  if (event.request.method !== "POST" || url.pathname !== "/share-target") return

  // A6 review fix (MEDIUM 1): a hostile page can auto-submit a cross-site
  // form straight to this exact URL — the worker only sees the request's
  // destination, which is this origin either way, so `url.pathname` alone
  // cannot distinguish that from the OS's own share sheet. `Sec-Fetch-Site`
  // is set by the browser, not readable-or-writable from page JS: "cross-site"
  // for a hostile page's form, "none" (no referring page at all) for the
  // OS-level share-sheet launch this handler actually exists for. Falling
  // through to the network (no `event.respondWith`) rather than answering
  // with an error keeps this indistinguishable from a route this worker
  // never registered at all.
  if (event.request.headers.get("Sec-Fetch-Site") === "cross-site") return

  event.respondWith(handleShareTargetFetch(event))
})

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

// --- Widgets (Windows 11 / Android widget surface, packet A5's backend) -----
//
// No `widgetclick` listener: that event only fires for an `Action.Execute`
// verb-based action, and `public/widgets/streak.json`'s one action is
// `Action.OpenUrl` — the widget host opens it directly, so this worker never
// sees a click at all. A listener here would be dead code for a template
// that carries no verb to trigger it.

/**
 * The tag `vite/manifest.ts`'s `widgets` member declares for the one widget
 * this app ships. Hardcoded rather than read from anywhere importable here:
 * `vite/manifest.ts` is a Vite-config module, not part of this file's own
 * narrow `tsconfig.sw.json` project (see that file's own comment on why the
 * include list stays explicit), and there is exactly one widget to name.
 */
const STREAK_WIDGET_TAG = "lemely-streak"

/**
 * Render one widget instance with the caller's current data.
 *
 * The template is always fetched fresh from `widget.definition.msAcTemplate`
 * (never inlined) because the Adaptive Cards spec requires the *rendered*
 * template text in every `updateByTag` call, not just the data — there is no
 * "keep the template, only update the data" call in this API. The stub
 * fallback's URL comes from `widget.definition.data` — the exact value
 * `vite/manifest.ts`'s `widgets[0].data` declares — rather than a second,
 * hand-typed copy of that path living here too.
 */
async function renderWidget(widget: WidgetObject): Promise<void> {
  const template = await (await fetch(widget.definition.msAcTemplate)).text()
  const data = await fetchWidgetDataOrStub(
    self.clients,
    CLIENT_REPLY_TIMEOUT_MS,
    widget.definition.data,
    fetch,
  )
  await self.widgets.updateByTag(widget.definition.tag, { template, data })
}

// A widget is added to the dashboard without necessarily being rendered yet
// (Microsoft's own docs: "it is not automatically rendered using the
// ms_ac_template and data fields") — this is the event that asks this worker
// to actually draw it for the first time.
self.addEventListener("widgetinstall", (event) => {
  event.waitUntil(renderWidget(event.widget))
})

// Fired when the widget host resumes rendering installed widgets after
// suspending them to save resources — the moment this worker gets another
// chance at fresher data than whatever was last pushed, which may by now be
// the stub if no tab was open at install time.
self.addEventListener("widgetresume", (event) => {
  event.waitUntil(renderWidget(event.widget))
})

// A widget instance can already be installed — from before this worker code
// shipped, or from an install that landed with no page open to answer the
// handshake — with nothing to make it re-render on its own once one is.
// `activate` is the same moment `sw.ts`'s non-precache branch already uses to
// bring a returning visitor onto a fresh deploy (above); doing the same for
// an already-installed widget here means a reader never has to remove and
// re-add it just to see real data for the first time.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    self.widgets.getByTag(STREAK_WIDGET_TAG).then((widget) => {
      if (widget === undefined) return
      return renderWidget(widget)
    }),
  )
})

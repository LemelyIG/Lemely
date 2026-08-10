/*
 * The browser half of enabling web push, for G-12 (P5.9 chunk C).
 *
 * Split the same way chunk A split the service worker: the decisions live in
 * pure functions vitest can drive, and the `navigator`/`Notification` plumbing
 * around them is kept as thin as possible, because there is no jsdom here
 * (`vitest.config.ts:25`) and nothing that touches a browser global is testable.
 *
 * Nothing in this file is imported by `src/sw.ts`, and it must stay that way —
 * `tsconfig.sw.json` deliberately includes only `src/sw.ts` and
 * `src/lib/push/pushDecision.ts` so that reaching a page-only API from the
 * worker fails `web-typecheck` rather than failing at runtime on a reader's
 * device (D5.15 §2). Do not widen that include to this directory.
 */

/** The browser's own three-valued permission, restated so this module needs no DOM lib. */
export type PushPermission = "default" | "granted" | "denied"

export interface PushStateInputs {
  /** Does this browser have a service worker *and* a `PushManager` at all? */
  supported: boolean
  /** Does this deployment have VAPID keys? `GET /notifications/push/config`. */
  available: boolean
  permission: PushPermission
  /** Does this browser currently hold a subscription for this origin? */
  subscribed: boolean
}

/**
 * What G-12 shows instead of one grey button.
 *
 * `unavailable` is a **designed** state, not a failure (D5.9 §4): this build
 * ships with no VAPID keys, so `available: false` is the correct answer and must
 * not be rendered as an error. It is a different fact from the browser having
 * denied permission, and UI spec §G-12 asks for that difference explicitly —
 * "show that clearly with a route to fix it rather than toggles that silently do
 * nothing".
 */
export type PushState =
  | { kind: "unavailable" }
  | { kind: "unsupported" }
  | { kind: "denied" }
  | { kind: "prompt" }
  | { kind: "enabled" }

/**
 * Collapse the four independent facts into the one state to show.
 *
 * **Server availability is checked before browser support, and the order is the
 * point of this function.** Both are "push cannot happen here", but only one of
 * them is something the reader could act on — and acting on it would achieve
 * nothing. Telling someone on an unsupporting browser to switch browsers, when
 * the server has no keys to sign a push with either way, sends them on an errand
 * that ends in the same place. So the binding constraint no user action can
 * change is stated first, and the browser message is reserved for the case where
 * it is genuinely the only thing standing in the way.
 *
 * `granted` without a subscription resolves to `prompt`, not `enabled`: the
 * permission is the browser's memory of an earlier answer, while the
 * subscription is what the server can actually push to. A reader whose
 * subscription was dropped — a cleared site data, a new profile, a `410` the
 * server acted on (D5.9 §4) — would otherwise see "on" for something switched
 * off, which is the one failure this screen exists to prevent. Re-enabling from
 * `prompt` shows no permission dialog when permission is already granted, so the
 * recovery costs the reader a click and no interruption.
 */
export function resolvePushState(inputs: PushStateInputs): PushState {
  if (!inputs.available) return { kind: "unavailable" }
  if (!inputs.supported) return { kind: "unsupported" }
  if (inputs.permission === "denied") return { kind: "denied" }
  if (inputs.permission === "granted" && inputs.subscribed) return { kind: "enabled" }
  return { kind: "prompt" }
}

/**
 * Decode a VAPID public key into the `applicationServerKey` bytes
 * `pushManager.subscribe` requires.
 *
 * The server publishes the key as **base64url** (RFC 4648 §5, no padding), which
 * is what RFC 8292 specifies, and `atob` speaks only standard base64. So the two
 * substitutions and the padding are not defensive tidiness — without them a real
 * key either decodes to different bytes or throws `InvalidCharacterError`, and
 * the subscription is rejected by the push service with an error that says
 * nothing about why.
 *
 * Throws on input that is not decodable at all; the caller surfaces that as a
 * failed enable rather than a silently absent subscription.
 *
 * The return type is written as `Uint8Array<ArrayBuffer>` rather than the bare
 * `Uint8Array`, which since TypeScript 5.7 defaults its parameter to
 * `ArrayBufferLike` and so admits a `SharedArrayBuffer` that `BufferSource` —
 * and therefore `applicationServerKey` — does not. Not cosmetic: the bare form
 * fails `web-typecheck` at the `pushManager.subscribe` call.
 */
export function urlBase64ToUint8Array(base64Url: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64Url.length % 4)) % 4)
  const base64 = (base64Url + padding).replace(/-/g, "+").replace(/_/g, "/")
  const raw = atob(base64)
  const output = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i)
  return output
}

/** What `POST /notifications/push/subscribe` wants, mirroring `PushSubscribeRequestDTO`. */
export interface PushSubscribePayload {
  endpoint: string
  keys: { p256dh: string; auth: string }
}

/**
 * Reshape a `PushSubscription.toJSON()` into the subscribe body.
 *
 * Returns null when either key is missing rather than posting a partial
 * subscription: the server would store a row it can never encrypt to, and the
 * screen would then honestly report push as enabled while every send failed.
 * The browser types both keys as optional, and on some engines they genuinely
 * are absent, so this is a reachable input and not a formality.
 */
export function subscribePayloadFrom(json: unknown): PushSubscribePayload | null {
  if (typeof json !== "object" || json === null) return null
  const record = json as { endpoint?: unknown; keys?: unknown }
  if (typeof record.endpoint !== "string" || record.endpoint === "") return null
  if (typeof record.keys !== "object" || record.keys === null) return null
  const keys = record.keys as { p256dh?: unknown; auth?: unknown }
  if (typeof keys.p256dh !== "string" || typeof keys.auth !== "string") return null
  if (keys.p256dh === "" || keys.auth === "") return null
  return { endpoint: record.endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth } }
}

/** Whether this browser can do push at all. Both halves are required. */
export function pushSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    "serviceWorker" in navigator &&
    typeof window !== "undefined" &&
    "PushManager" in window &&
    "Notification" in window
  )
}

/** The browser's current permission, or `"default"` where the API does not exist. */
export function currentPushPermission(): PushPermission {
  if (typeof window === "undefined" || !("Notification" in window)) return "default"
  return Notification.permission as PushPermission
}

/** The subscription this browser already holds for this origin, if any. */
export async function currentPushSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null
  const registration = await navigator.serviceWorker.ready
  return await registration.pushManager.getSubscription()
}

/**
 * Ask for permission and subscribe, returning the body to POST.
 *
 * Returns null for every outcome that is not a usable subscription — a refused
 * prompt, an unsupported browser, a subscription whose keys the engine withheld.
 * The caller re-reads the real state afterwards rather than assuming success, so
 * a null here becomes an honest "still off" rather than an error dialog for
 * something the reader chose.
 */
export async function subscribeToPush(publicKey: string): Promise<PushSubscribePayload | null> {
  if (!pushSupported()) return null
  const permission = await Notification.requestPermission()
  if (permission !== "granted") return null

  const registration = await navigator.serviceWorker.ready
  const existing = await registration.pushManager.getSubscription()
  // Re-posting an existing subscription is deliberate rather than skipped: the
  // server row can be gone (a `410` it acted on, a different account on this
  // browser) while the browser's own subscription survives, and the subscribe
  // endpoint is idempotent per endpoint by design.
  const subscription =
    existing ??
    (await registration.pushManager.subscribe({
      // Required by every current engine; a push that could be delivered to a
      // hidden handler is not a push this app would ever send anyway — D5.10's
      // payload-less design always renders a notification.
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    }))

  return subscribePayloadFrom(subscription.toJSON())
}

/**
 * Drop this browser's subscription, returning the endpoint the server should
 * forget, or null if there was nothing to drop.
 *
 * The browser-side unsubscribe happens first and its result is not required to
 * succeed: an engine that refuses still leaves a server row that must go, and a
 * stale local subscription is harmless once nothing can be pushed to it.
 */
export async function unsubscribeFromPush(): Promise<string | null> {
  const subscription = await currentPushSubscription()
  if (subscription === null) return null
  const endpoint = subscription.endpoint
  await subscription.unsubscribe().catch(() => false)
  return endpoint
}

/**
 * Show a notification from this device, with no server involved.
 *
 * **This is not a delivery test and the screen must not call it one.** No route
 * in this backend sends a test push, and on a build with no VAPID keys none
 * could. What it does prove is the half that actually breaks in practice: that
 * permission is granted, that the service worker is registered and active, and
 * that the operating system will surface a Lemely notification rather than
 * swallowing it. A reader who sees nothing after pressing this has learned
 * something real about their device.
 *
 * Goes through the service-worker registration rather than `new Notification()`
 * because that constructor is unsupported on Android Chrome and is exactly where
 * a hand-rolled test button silently does nothing on the platform most of these
 * students are on.
 */
export async function showLocalTestNotification(): Promise<boolean> {
  if (!pushSupported() || currentPushPermission() !== "granted") return false
  const registration = await navigator.serviceWorker.ready
  await registration.showNotification("Lemely", {
    body: "Notifications are working on this device.",
    icon: "/pwa-192x192.png",
    badge: "/pwa-192x192.png",
    // The same shape `sw.ts` gives a real push, so tapping it exercises the real
    // `notificationclick` handler instead of a special case that proves nothing.
    data: { url: "/student/notifications" },
  })
  return true
}

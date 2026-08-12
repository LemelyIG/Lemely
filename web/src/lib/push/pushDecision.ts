/**
 * What a push notification should render — decided as pure data, with no
 * service-worker API anywhere in this file.
 *
 * This module exists because of D5.15 §4. A push carries **no payload**
 * (D5.10), so the service worker has to obtain its content from somewhere at
 * the moment the push arrives, and it cannot do the authenticated fetch itself:
 * the session token lives in `localStorage` (`lib/auth/storage.ts`), which does
 * not exist in a `ServiceWorkerGlobalScope`. The SW therefore asks an open page
 * for the content and the page — which *can* read the token — replies over
 * `postMessage`.
 *
 * That makes the interesting branch a data question ("did a usable reply come
 * back, or do we fall back?") rather than an event-plumbing one, and this file
 * is the half that `vitest` can drive. `sw.ts` is the thin adapter around it.
 * vitest runs `environment: "node"` with no jsdom (`vitest.config.ts:25`) and
 * there is no `ServiceWorkerGlobalScope` to mount in any case, so a pure
 * function is not merely the tidy seam here — it is the only testable one.
 *
 * Two invariants every export below preserves:
 *
 * 1. **Something is always returned.** Browsers require *some* notification per
 *    push; a handler that resolves without calling `showNotification` triggers
 *    the engine's own "This site has been updated in the background" message.
 *    So there is no "show nothing" branch to design, and nothing here throws.
 * 2. **A reply is untrusted input.** It arrives over a message channel, so it
 *    is validated like any other wire data rather than destructured on faith.
 *    It is also necessarily *plain* data — `postMessage` structured-clones, so
 *    no getter or class instance can reach here — which is why these functions
 *    validate shapes rather than defending against hostile property access. The
 *    unconditional "a notification is always shown" guarantee lives in `sw.ts`,
 *    wrapped around the call, because that is where the browser requirement is.
 */

/** Content the service worker passes to `showNotification`. */
export interface PushNotificationContent {
  title: string
  body: string
  /**
   * Same-origin path to open on click. Always a rooted relative path — see
   * `sameOriginPath` for why an absolute URL is never accepted.
   */
  url: string
}

/**
 * Shown when no open page answered in time, or answered with something
 * unusable. This is the *expected* state whenever the app is fully closed, not
 * an error path: it is the standing cost of D5.10's payload-less push plus
 * D5.15 §2's refusal to keep a credential in the worker. Carried to the Phase-5
 * limitations rather than hidden behind a comment.
 */
export const GENERIC_PUSH_TITLE = "Lemely"
export const GENERIC_PUSH_BODY = "You have a new notification"

/**
 * Where a notification with no better destination sends the reader.
 *
 * The app root, not an inbox path, and deliberately so: this API is
 * role-agnostic because `at_risk_alert` is addressed to a **teacher and a
 * parent**, and neither portal has an inbox screen in this build. `/` routes by
 * role, so it is the one destination that cannot 404 for the reader who
 * received the push.
 */
export const DEFAULT_PUSH_URL = "/"

/**
 * How long the worker waits for a page to answer before rendering the generic
 * notification. Short on purpose: the push event's lifetime is bounded by the
 * browser, and a slow answer is worth less than a prompt honest fallback.
 */
export const CLIENT_REPLY_TIMEOUT_MS = 1500

/** The message a worker sends to a page to ask what just arrived. */
export const PUSH_CONTENT_REQUEST = "lemely:push-content-request"

/** The message a page sends back. */
export const PUSH_CONTENT_REPLY = "lemely:push-content-reply"

/** Trim a value that should be a non-empty string, or return null. */
function nonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") return null
  const trimmed = value.trim()
  return trimmed === "" ? null : trimmed
}

/**
 * Accept only a rooted, same-origin path.
 *
 * The click target arrives over a message channel, and a notification is a
 * privileged-feeling surface: a reader who taps one has every reason to believe
 * they are still inside the app. Accepting an absolute URL would let anything
 * able to post into that channel choose the destination, so the check is a
 * whitelist of shapes rather than a blacklist of schemes.
 *
 * `//evil.example` is rejected explicitly — it *looks* rooted but is a
 * protocol-relative URL that navigates off-origin, which is precisely the case
 * a naive `startsWith("/")` test lets through.
 */
export function sameOriginPath(value: unknown): string | null {
  const path = nonEmptyString(value)
  if (path === null) return null
  if (!path.startsWith("/")) return null
  if (path.startsWith("//")) return null
  // A backslash is normalised to a forward slash by some engines' URL parsers,
  // so `/\evil.example` can escape the origin the same way `//` does.
  if (path.startsWith("/\\")) return null
  return path
}

/**
 * Turn whatever a page replied with into something renderable.
 *
 * Returns the generic notification for every unusable input — no reply, a
 * non-object, a missing title — because of invariant 1 above.
 *
 * A **missing body is not unusable**: `NotificationDTO.body` is genuinely
 * nullable on the backend (`schemas_notifications.py`), so a real notification
 * can carry a title alone. Such a reply keeps its real title and borrows the
 * generic body, rather than being discarded down to a fully generic
 * notification that would throw away the one true thing we know.
 */
export function decidePushNotification(reply: unknown): PushNotificationContent {
  const fallback: PushNotificationContent = {
    title: GENERIC_PUSH_TITLE,
    body: GENERIC_PUSH_BODY,
    url: DEFAULT_PUSH_URL,
  }

  if (reply === null || typeof reply !== "object") return fallback

  const candidate = reply as Record<string, unknown>
  const title = nonEmptyString(candidate.title)
  if (title === null) return fallback

  return {
    title,
    body: nonEmptyString(candidate.body) ?? GENERIC_PUSH_BODY,
    url: sameOriginPath(candidate.url) ?? DEFAULT_PUSH_URL,
  }
}

/**
 * Pick the page to focus when a notification is clicked.
 *
 * Prefers an already-focused page, then any visible one, then whatever exists —
 * so a click lands in the window the reader was last using instead of
 * arbitrarily resurrecting the oldest tab. Returns null when nothing is open,
 * which is the caller's signal to open a new window.
 *
 * Typed structurally rather than against `WindowClient` so this file stays free
 * of service-worker lib types and can be compiled under the app's DOM-only
 * `tsconfig`.
 */
export interface FocusableClient {
  readonly focused?: boolean
  readonly visibilityState?: string
}

export function pickClientToFocus<T extends FocusableClient>(clients: readonly T[]): T | null {
  if (clients.length === 0) return null
  const focused = clients.find((client) => client.focused === true)
  if (focused !== undefined) return focused
  const visible = clients.find((client) => client.visibilityState === "visible")
  if (visible !== undefined) return visible
  return clients[0]
}

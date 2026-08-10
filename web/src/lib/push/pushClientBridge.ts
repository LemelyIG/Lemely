/*
 * The page half of the push handshake (D5.15 §2).
 *
 * A push carries no payload (D5.10) and the service worker cannot fetch the
 * inbox itself — the bearer token lives in `localStorage`, which a
 * `ServiceWorkerGlobalScope` cannot read. So the worker asks, and this module
 * answers: the page does the authenticated fetch and posts the title and body
 * back over the `MessagePort` the worker supplied.
 *
 * Without this listener every push renders the generic "You have a new
 * notification" even with a tab open, and the whole reason for choosing a
 * client handshake over mirroring the credential into IndexedDB is lost.
 *
 * The credential never leaves this context: the worker receives rendered text,
 * never a token.
 */

import { request } from "@/lib/api"
import type { NotificationsPage } from "@/lib/notificationTypes"
import { PUSH_CONTENT_REPLY, PUSH_CONTENT_REQUEST } from "@/lib/push/pushDecision"

/** What this module posts back to the worker. */
export interface PushContentReply {
  type: typeof PUSH_CONTENT_REPLY
  title: string
  body: string | null
  url: string
}

/**
 * Where a push of a given type sends the reader.
 *
 * Only `announcement` gets a specific screen. `grade_ready` deliberately does
 * not: its payload carries the upload's UUID, and the only per-paper route
 * (`/student/result/:paperId`) addresses papers by **history index** and 404s on
 * a UUID (`routers/student.py:487`). Linking it would ship a guaranteed dead
 * link. The three time-triggered types have no screen at all.
 *
 * Everything else goes to `/`, which routes the reader to their own portal by
 * role. That matters because this API is role-agnostic on purpose:
 * `at_risk_alert` is addressed to a **teacher and a parent**, neither of whom
 * has an inbox screen in this build, so a hardcoded student path would 404 for
 * exactly the audience that notification was written for.
 *
 * Kept consistent with `Notifications.destinationFor` so a push and the inbox
 * row it announces land in the same place.
 */
function destinationFor(type: string): string {
  switch (type) {
    case "announcement":
      return "/student/announcements"
    default:
      return "/"
  }
}

/**
 * Build the worker's reply from a page of the inbox.
 *
 * Returns null when there is nothing unread to announce — the worker then
 * renders its generic notification, which is the honest outcome: a push
 * arrived, but this page cannot say what it was about.
 *
 * **The newest unread row is used, not the newest row.** A push announces
 * something new; describing it with a notification the reader has already
 * opened would be actively misleading, and is the failure mode a naive
 * `notifications[0]` produces the moment a read row sits at the top.
 */
export function buildPushReply(page: NotificationsPage | null): PushContentReply | null {
  if (page === null) return null
  const unread = page.notifications.find((notification) => notification.readAt === null)
  if (unread === undefined) return null
  return {
    type: PUSH_CONTENT_REPLY,
    title: unread.title,
    body: unread.body,
    url: destinationFor(unread.type),
  }
}

/**
 * Answer one request from the worker.
 *
 * Exported for tests, which drive it with a fake fetcher — there is no jsdom
 * here (`vitest.config.ts:25`), so the real `navigator.serviceWorker` plumbing
 * in `registerPushClientBridge` is not itself unit-testable and is kept as thin
 * as possible around this function.
 */
export async function answerPushContentRequest(
  fetchInbox: () => Promise<NotificationsPage>,
): Promise<PushContentReply | null> {
  try {
    return buildPushReply(await fetchInbox())
  } catch {
    // A failed or unauthorised fetch is not an error worth surfacing anywhere:
    // the worker's fallback already covers it, and there is no UI in scope
    // during a push. Returning null is the same signal as "nothing unread".
    return null
  }
}

/**
 * Wire the listener up to the real service worker.
 *
 * Safe to call when there is no service worker at all (an unsupported browser,
 * or the dev server, which does not generate one) — it simply does nothing.
 */
export function registerPushClientBridge(): void {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return

  navigator.serviceWorker.addEventListener("message", (event: MessageEvent) => {
    const data: unknown = event.data
    if (
      typeof data !== "object" ||
      data === null ||
      (data as { type?: unknown }).type !== PUSH_CONTENT_REQUEST
    ) {
      return
    }

    const port = event.ports[0]
    if (port === undefined) return

    void answerPushContentRequest(() =>
      request<NotificationsPage>("/notifications?unreadOnly=true&limit=1"),
    ).then((reply) => {
      // Always post something, even null: the worker races this against a
      // timeout, and a definite "nothing to say" lets it render the generic
      // notification immediately instead of waiting out the full timeout.
      port.postMessage(reply)
    })
  })
}

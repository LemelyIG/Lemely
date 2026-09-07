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
import { getSession } from "@/lib/auth/storage"
import type { Notification, NotificationsPage } from "@/lib/notificationTypes"
import {
  DEFAULT_PUSH_URL,
  PUSH_CONTENT_REPLY,
  PUSH_CONTENT_REQUEST,
} from "@/lib/push/pushDecision"

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
 * Four of the five types have a specific screen. `grade_ready` deliberately
 * does not: its payload carries the upload's UUID, and the only per-paper
 * route (`/student/result/:paperId`) addresses papers by **history index**
 * and 404s on a UUID (`routers/student.py:487`). Linking it would ship a
 * guaranteed dead link, so it keeps `DEFAULT_PUSH_URL`.
 *
 * `at_risk_alert` is addressed to a **teacher and a parent**, and each has
 * their own inbox (`/teacher/notifications`, `/parent/notifications`), so the
 * viewer's role decides. `school_admin` reads the teacher portal. With no role
 * known the answer is `/`, which routes by role and cannot 404 for whoever
 * received the push. This comment used to say neither portal had an inbox
 * screen; both do now, and the fallback stays for the reason above.
 *
 * Kept consistent with the student `Notifications.destinationFor` so a push
 * and the inbox row it announces land in the same place. The two differ only
 * where they must: the inbox screen returns `null` for "no action" and this
 * returns `DEFAULT_PUSH_URL`, because a click has to go somewhere.
 */
export function destinationFor(
  notification: Pick<Notification, "type" | "payload">,
  role: string | undefined,
): string {
  switch (notification.type) {
    case "announcement":
      return "/student/announcements"
    case "streak_warning":
      return "/student/profile"
    case "study_plan_reminder": {
      const { subjectCode, sessionId } = notification.payload
      if (!subjectCode || !sessionId) return DEFAULT_PUSH_URL
      return `/student/plan/${encodeURIComponent(subjectCode)}/session/${encodeURIComponent(sessionId)}`
    }
    case "at_risk_alert":
      if (role === "teacher" || role === "school_admin") return "/teacher/notifications"
      if (role === "parent") return "/parent/notifications"
      return DEFAULT_PUSH_URL
    default:
      return DEFAULT_PUSH_URL
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
export function buildPushReply(
  page: NotificationsPage | null,
  role?: string,
): PushContentReply | null {
  if (page === null) return null
  const unread = page.notifications.find((notification) => notification.readAt === null)
  if (unread === undefined) return null
  return {
    type: PUSH_CONTENT_REPLY,
    title: unread.title,
    body: unread.body,
    url: destinationFor(unread, role),
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
  role?: string,
): Promise<PushContentReply | null> {
  try {
    return buildPushReply(await fetchInbox(), role)
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

    void answerPushContentRequest(
      () => request<NotificationsPage>("/notifications?unreadOnly=true&limit=1"),
      // The role is read at answer time, not at registration: a page can
      // outlive a sign-out and sign-in as someone else.
      getSession()?.role,
    ).then((reply) => {
      // Always post something, even null: the worker races this against a
      // timeout, and a definite "nothing to say" lets it render the generic
      // notification immediately instead of waiting out the full timeout.
      port.postMessage(reply)
    })
  })
}

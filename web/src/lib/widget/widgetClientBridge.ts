/*
 * The page half of the widget handshake — same shape and same reason as
 * `lib/push/pushClientBridge.ts` (D5.15 §2): the worker cannot read
 * `localStorage`, so it cannot make the authenticated `GET
 * /api/student/widget` request itself. This module answers: the page does
 * the fetch and posts the streak and next-session data back over the
 * `MessagePort` the worker supplied.
 *
 * Without this listener the widget the reader adds to their Widgets Board
 * never renders real data — see `sw/widgetBridge.ts`'s own header for the
 * fallback that covers it, and its "known limitation" note on how fresh the
 * widget can ever be.
 *
 * The credential never leaves this context: the worker receives rendered
 * numbers, never a token.
 */

import { request } from "@/lib/api"
import { getSession } from "@/lib/auth/storage"
import {
  WIDGET_DATA_REPLY,
  WIDGET_DATA_REQUEST,
  type StudentWidgetData,
} from "@/sw/widgetBridge"

/** What this module posts back to the worker. */
export interface WidgetDataReply {
  type: typeof WIDGET_DATA_REPLY
  streak: number
  nextSession: StudentWidgetData["nextSession"]
}

/**
 * Answer one request from the worker.
 *
 * Exported for tests, which drive it with a fake fetcher — there is no jsdom
 * here (`vitest.config.ts:25`), so the real `navigator.serviceWorker`
 * plumbing in `registerWidgetClientBridge` is not itself unit-testable and
 * is kept as thin as possible around this function.
 *
 * `GET /api/student/widget` is gated `require_role(Role.student)`
 * (`lemely/web/routers/widget.py`) — a signed-in teacher, parent or admin
 * tab would just get a 403 the same as no reply at all, so the role check
 * below skips the fetch entirely rather than surfacing that as a failed
 * request for every non-student tab that happens to be open.
 */
export async function answerWidgetDataRequest(
  fetchWidget: () => Promise<StudentWidgetData>,
  role: string | undefined,
): Promise<WidgetDataReply | null> {
  if (role !== "student") return null
  try {
    const data = await fetchWidget()
    return { type: WIDGET_DATA_REPLY, streak: data.streak, nextSession: data.nextSession }
  } catch {
    // A failed or unauthorised fetch is not an error worth surfacing
    // anywhere: the worker's stub fallback already covers it, and there is
    // no UI in scope for a background widget render. Returning null is the
    // same signal as "nothing to say".
    return null
  }
}

/**
 * Wire the listener up to the real service worker.
 *
 * Safe to call when there is no service worker at all (an unsupported
 * browser, or the dev server, which does not generate one) — it simply does
 * nothing.
 */
export function registerWidgetClientBridge(): void {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return

  navigator.serviceWorker.addEventListener("message", (event: MessageEvent) => {
    const data: unknown = event.data
    if (
      typeof data !== "object" ||
      data === null ||
      (data as { type?: unknown }).type !== WIDGET_DATA_REQUEST
    ) {
      return
    }

    const port = event.ports[0]
    if (port === undefined) return

    void answerWidgetDataRequest(
      () => request<StudentWidgetData>("/student/widget"),
      // Read at answer time, not at registration: a page can outlive a
      // sign-out and sign-in as someone else.
      getSession()?.role,
    ).then((reply) => {
      // Always post something, even null: the worker races this against a
      // timeout, and a definite "nothing to say" lets it fall back to the
      // stub immediately instead of waiting out the full timeout.
      port.postMessage(reply)
    })
  })
}

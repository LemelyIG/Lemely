/*
 * What the teacher and parent inboxes decide (push-delivery spec §6).
 *
 * Per-portal screens, not a shared one: only `at_risk_alert` ever reaches
 * these two roles, and the same alert reads differently to each — a teacher
 * sees a student they teach, a parent sees their own child. What the two
 * screens share is this module, not chrome: the decisions the web runner can
 * pin (it has no DOM), so a screen that misroutes a row or hides mark-all
 * fails a test rather than a reader.
 *
 * The student inbox (`portals/student/screens/Notifications.tsx`) is not
 * extracted or refactored into this; it keeps its own `destinationFor`.
 */

import type { Notification, NotificationCounts, NotificationsPage } from "@/lib/notificationTypes"

export type StaffRole = "teacher" | "parent"

/**
 * Where a row's "Open" goes, or null for no action.
 *
 * `payload.studentId` is the server-side relationship the alert was raised
 * from (`_alert_teachers_and_parents`), so linking to it never trusts a
 * caller. A row without one renders with no action rather than a link that
 * cannot resolve. A type with no screen for the role returns null, and every
 * id is encoded before it is spliced into a path.
 *
 * The tutoring notices (SPEC docs/tutoring/SPEC.md section b.4) are routed here
 * too: the tutor-side ones land in the teacher inbox, the family-side ones in
 * the parent inbox.
 */
export function staffDestinationFor(
  role: StaffRole,
  notification: Pick<Notification, "type" | "payload">,
): string | null {
  const { type, payload } = notification
  if (type === "at_risk_alert") {
    const studentId = payload.studentId
    if (!studentId) return null
    const id = encodeURIComponent(studentId)
    return role === "teacher" ? `/teacher/students/${id}` : `/parent/children/${id}`
  }
  return role === "teacher" ? tutorDestinationFor(type, payload) : parentDestinationFor(type, payload)
}

/** A tutor's own tutoring screens (SPEC section d, T-15 to T-21). Ids only in the payload. */
function tutorDestinationFor(type: string, payload: Record<string, string>): string | null {
  switch (type) {
    case "booking_request":
    case "booking_update":
    case "booking_note":
      return payload.bookingId
        ? `/teacher/tutoring/sessions/${encodeURIComponent(payload.bookingId)}`
        : null
    case "tutor_access":
      return "/teacher/tutoring/students"
    case "tutor_review":
      return "/teacher/tutoring/preview"
    case "tutor_listing":
      return "/teacher/tutoring/profile"
    default:
      return null
  }
}

/**
 * A parent's tutoring screens (P-05, P-06, P-08). A booking notice needs both ids: the child
 * the session belongs to, and the session. A parent-link notice has no subject left to open,
 * so it goes to the list of children.
 */
function parentDestinationFor(type: string, payload: Record<string, string>): string | null {
  const child = payload.studentId ? encodeURIComponent(payload.studentId) : null
  switch (type) {
    case "booking_update":
    case "booking_note":
      return child !== null && payload.bookingId
        ? `/parent/children/${child}/sessions/${encodeURIComponent(payload.bookingId)}`
        : null
    case "tutor_access":
      if (child === null) return null
      // A class-join notice is about tutoring in general; a grant notice is about who has access.
      return payload.enrollmentId
        ? `/parent/children/${child}/tutoring`
        : `/parent/children/${child}/tutor-access`
    case "parent_link":
      return "/parent"
    default:
      return null
  }
}

export function isInboxEmpty(page: NotificationsPage): boolean {
  return page.notifications.length === 0
}

export function unreadCountOf(page: NotificationsPage): number {
  return page.notifications.filter((n) => n.readAt === null).length
}

/** Mark-all is offered only while it would change something. */
export function showMarkAllRead(page: NotificationsPage): boolean {
  return unreadCountOf(page) > 0
}

/**
 * The nav badge's text, or null for no badge. Null for pending and error too:
 * a badge that flashes "0" or guesses during a load says something the app
 * does not yet know. Capped so a long-neglected inbox cannot widen the nav.
 */
export function unreadBadgeLabel(counts: NotificationCounts | undefined): string | null {
  if (counts === undefined || counts.unread <= 0) return null
  return counts.unread > 99 ? "99+" : String(counts.unread)
}

/** Same rule as the student inbox: an unknown type renders with its raw name
 * rather than hiding the row. */
export function staffTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    at_risk_alert: "Needs attention",
    announcement: "Announcement",
    grade_ready: "Marked",
    streak_warning: "Streak",
    study_plan_reminder: "Study plan",
    // Task 9 (D10): a student's own deletion withdrew a review item a
    // teacher had open. Non-navigable, same as every other row here — the
    // withdrawn item 403s if opened, so there is nowhere for a click to go.
    review_withdrawn: "Review withdrawn",
    // The tutoring marketplace's notices (SPEC docs/tutoring/SPEC.md section b.4).
    booking_request: "Session request",
    booking_update: "Session update",
    booking_note: "Session note",
    tutor_access: "Progress sharing",
    tutor_review: "Review decision",
    tutor_listing: "Tutor profile",
    parent_link: "Parent link",
    tutoring_report: "Safety report",
  }
  return labels[type] ?? type
}

/** One error wording for both: the failure is the same connection problem. */
export const STAFF_INBOX_ERROR = {
  heading: "Notifications could not be loaded",
  body: "This is a connection problem on our side. You may well have notifications waiting, and nothing has been lost.",
}

export const TEACHER_INBOX_EMPTY = {
  heading: "Nothing yet",
  body: "When a student you teach may need support, it will appear here.",
}

export const PARENT_INBOX_EMPTY = {
  heading: "Nothing yet",
  body: "When your child may need support, it will appear here.",
}

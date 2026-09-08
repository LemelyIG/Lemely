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
 * cannot resolve. Any other type has no screen for these roles and, in
 * practice, never reaches them.
 */
export function staffDestinationFor(
  role: StaffRole,
  notification: Pick<Notification, "type" | "payload">,
): string | null {
  if (notification.type !== "at_risk_alert") return null
  const studentId = notification.payload.studentId
  if (!studentId) return null
  const id = encodeURIComponent(studentId)
  return role === "teacher" ? `/teacher/students/${id}` : `/parent/children/${id}`
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

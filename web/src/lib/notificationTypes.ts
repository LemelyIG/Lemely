/*
 * Wire types for G-13's inbox, mirroring `lemely/web/schemas_notifications.py`.
 *
 * The router mounts at **`/api/notifications`**, not `/api/student/...`, and
 * that is deliberate on the backend's side: `at_risk_alert` is addressed to a
 * teacher and a parent, so a student-role gate would have built an inbox two of
 * its three intended audiences could not read. Nothing here is student-specific
 * for the same reason.
 */

/**
 * Every `NotificationType` value the backend can send, in the enum's order
 * (`lemely/db/models/enums.py`; a unit test reads that file and fails on drift).
 *
 * A union rather than a `string` so a screen that routes on the type gets a
 * compile error when the backend grows another, instead of silently falling
 * through to a default. The first six predate the tutoring marketplace; the last
 * eight are its notices (SPEC docs/tutoring/SPEC.md section a.1).
 *
 * UI spec section G-12 also lists a "weekly summary" toggle. There is
 * deliberately no `weekly_summary` member here: the enum has no matching column,
 * no sender and no row, and offering a switch that gates nothing is what UI spec
 * section 1.4 forbids.
 */
export const NOTIFICATION_TYPES = [
  "grade_ready",
  "announcement",
  "streak_warning",
  "study_plan_reminder",
  "at_risk_alert",
  "review_withdrawn",
  "booking_request",
  "booking_update",
  "booking_note",
  "tutor_access",
  "tutor_review",
  "tutor_listing",
  "parent_link",
  "tutoring_report",
] as const

export type NotificationType = (typeof NOTIFICATION_TYPES)[number]

/** The eight types the tutoring marketplace added: the tail of `NOTIFICATION_TYPES`. */
export const TUTORING_NOTIFICATION_TYPES = NOTIFICATION_TYPES.slice(-8)

export interface Notification {
  notificationId: string
  /**
   * Sent as the enum's string name. Typed as the union above plus `string` so
   * an unrecognised value from a newer backend renders as a plain notification
   * rather than crashing the list — an inbox that fails closed on one unknown
   * row is worse than one that shows it without an icon.
   */
  type: NotificationType | (string & {})
  title: string
  body: string | null
  /**
   * Identifiers only — an upload id, an announcement id. The backend types this
   * as `dict[str, str]` precisely so it can never carry a mark (D5.9 §2), and
   * the same constraint is restated here rather than widened to `unknown`.
   */
  payload: Record<string, string>
  createdAt: string
  /** `null` means unread. First-read time; re-marking does not move it. */
  readAt: string | null
}

export interface NotificationsPage {
  notifications: Notification[]
}

export interface NotificationCounts {
  unread: number
  total: number
  /**
   * Types with no unread rows are **absent rather than zero**, so a consumer
   * must treat a missing key as 0 and not assume every type appears.
   */
  unreadByType: Record<string, number>
}

export interface NotificationReadReceipt {
  notificationId: string
  readAt: string
}

export interface MarkAllReadResult {
  /** How many rows actually changed; a second call returns 0. */
  markedRead: number
}

/**
 * Whether this deployment can send web push at all.
 *
 * `available: false` is a **first-class, designed state**, not a failure: this
 * build ships with no VAPID keys, so the transport reports itself unavailable
 * by design (D5.9 §4). It is distinct from the browser having denied
 * permission, and G-12 must show the two differently.
 */
export interface PushConfig {
  available: boolean
  publicKey: string | null
}

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
 * The five `NotificationType` values the backend can send. Kept as a union
 * rather than a `string` so a screen that routes on the type gets a compile
 * error when the backend grows a sixth, instead of silently falling through to
 * a default.
 *
 * UI spec §G-12 also lists a "weekly summary" toggle. There is deliberately no
 * `weekly_summary` member here: the enum has exactly five values, no column, no
 * sender and no row, and offering a switch that gates nothing is what UI spec
 * §1.4 forbids.
 */
export type NotificationType =
  | "grade_ready"
  | "announcement"
  | "streak_warning"
  | "study_plan_reminder"
  | "at_risk_alert"

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

/*
 * C-20 · what each effective booking state looks and reads like (SPEC §a.3, §d).
 *
 * "Icon + text per effective state; never colour alone." The eight states are
 * `EffectiveState` (SPEC §b.3): the seven stored states plus `awaiting_outcome`,
 * which is derived at read time. `Record<EffectiveState, …>` makes a state added
 * to the type without a row here a compile error, and `bookingStatus.test.ts`
 * reads the SPEC's own tables to check the other direction.
 *
 * Icons are named here and drawn in `booking-status.tsx`, so this module stays
 * free of React and the node-only runner can read it. Each state has a label of
 * its own and an icon of its own: removing the colour leaves eight different
 * words and eight different shapes.
 *
 * Tones follow PRODUCT.md: amber for "needs attention" (a session with no
 * recorded outcome, a no-show), never red; a state that simply ended without a
 * session (declined, cancelled, expired) is neutral.
 */

import type { EffectiveState } from "@/lib/tutoringTypes"

export type BookingStatusIcon =
  | "HourglassMedium"
  | "CalendarCheck"
  | "ClipboardText"
  | "CheckCircle"
  | "XCircle"
  | "Prohibit"
  | "UserMinus"
  | "CalendarX"

export type BookingStatusTone = "info" | "ok" | "warn" | "neutral"

export interface BookingStatus {
  label: string
  icon: BookingStatusIcon
  tone: BookingStatusTone
}

/** In the order a session moves through them. */
export const EFFECTIVE_STATES: readonly EffectiveState[] = [
  "requested",
  "accepted",
  "awaiting_outcome",
  "completed",
  "declined",
  "cancelled",
  "no_show",
  "expired",
]

export const BOOKING_STATUS: Record<EffectiveState, BookingStatus> = {
  requested: { label: "Waiting for reply", icon: "HourglassMedium", tone: "info" },
  accepted: { label: "Confirmed", icon: "CalendarCheck", tone: "ok" },
  awaiting_outcome: { label: "Awaiting outcome", icon: "ClipboardText", tone: "warn" },
  completed: { label: "Completed", icon: "CheckCircle", tone: "ok" },
  declined: { label: "Declined", icon: "XCircle", tone: "neutral" },
  cancelled: { label: "Cancelled", icon: "Prohibit", tone: "neutral" },
  no_show: { label: "No-show", icon: "UserMinus", tone: "warn" },
  expired: { label: "Expired", icon: "CalendarX", tone: "neutral" },
}

export function bookingStatusOf(state: EffectiveState): BookingStatus {
  return BOOKING_STATUS[state]
}

/** For a screen that needs the state as one phrase, e.g. a row's accessible name. */
export function bookingStatusAriaLabel(state: EffectiveState): string {
  return `Session status: ${BOOKING_STATUS[state].label}`
}

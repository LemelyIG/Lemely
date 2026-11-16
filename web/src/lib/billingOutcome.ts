import { ApiError } from "@/lib/api"
import { PHONE_CHECKOUT_HEADING, isCheckoutPhoneRequired } from "@/lib/phone"

/*
 * What a payer is told when a billing write fails. Every billing write inserts its payment row
 * before calling Paymob (spec §6), so a failed request never charged anyone, and saying so is
 * the one thing a payer most needs to hear. Status-first: the backend's own messages are
 * written for client authors, not payers. Every line is as short as it can be.
 *
 * Error bodies differ by phase (M11): Phase 03 sends `detail: {code, message}`, Phases 05/06
 * `detail: {error, message}`, Phase 02 a plain-string `detail`. `billingErrorCode` reads both
 * object shapes.
 *
 * Statuses come from the backend (`_CHARGE_STATUS` in routers/billing.py): 404 not found, 422
 * `invalid_seats` and `invalid_settings`, 503 `payments_unavailable`, 403 `unknown_payer`, and
 * every other charge refusal is a 409. `seats_over_limit` and `seats_changing` are payment void
 * reasons only, never error codes.
 */

export function billingErrorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null
  const d = err.detail as { code?: unknown; error?: unknown } | undefined
  if (!d || typeof d !== "object") return null
  if (typeof d.code === "string") return d.code
  return typeof d.error === "string" ? d.error : null
}

/** 409 refusals. */
const CONFLICTS: Record<string, string> = {
  already_subscribed: "You already have an active plan. Change it from billing.",
  no_saved_card: "No saved card. Buy a credit pack by card once to save one.",
  seats_in_use: "Too many students hold seats. Remove some first. A removed seat frees up at month end.",
  seats_insufficient: "That plan has fewer seats than your students. Remove some first.",
  seats_exceed_new_tier: "That plan has fewer seats than your students. Remove some first.",
  charge_in_flight: "A payment is already being confirmed. Wait a minute, then try again.",
  plan_change_pending: "A plan change is already scheduled.",
  downgrade_unavailable: "This can't be scheduled as a downgrade now. Nothing changed. You can still cancel it.",
  period_ending: "This period ends too soon. Try again after renewal.",
  seat_reduction_pending: "A seat reduction is already scheduled.",
  seat_charge_overdue: "The last seat charge is unpaid. Check your card, then try again.",
  managed_by_another_payer: "Someone else pays for this account.",
  no_free_seat: "No free seats. Ask the teacher to add one.",
  invite_already_redeemed: "That invite was already used. Ask for a new one.",
  invite_limit: "Too many open invites. Revoke one first.",
  not_an_upgrade: "That isn't an upgrade.",
  not_a_teacher_plan: "Extra seats are for teacher plans only.",
  subscription_not_active: "Your plan isn't active right now. Check billing, then try again.",
  upgrade_unavailable: "This plan can't be upgraded now. Nothing was charged.",
  seat_reduction_unavailable: "Seats can't be reduced now. Nothing changed.",
  seat_reduction_locked: "Reduction locked. You can change it at your next renewal.",
  settings_changing: "Settings just changed. Reload and try again.",
  cap_below_pack_price: "Your monthly limit is below the pack price. Raise it to keep auto top-up working.",
}

/** 422 refusals from the charge routes. */
const INVALID: Record<string, string> = {
  invalid_seats: "That's over the extra-seat limit. Try fewer.",
  // The first checkout's refusal for the same thing (the service checks the admin-set ceiling).
  invalid_extra_seats: "That's over the extra-seat limit. Try fewer.",
  invalid_settings: "Those settings aren't valid. Check them and try again.",
}

/**
 * Refusals that will fail the same way if the payer presses the button again, so the button
 * stays off until the input changes. Every attempt spends one of the payer's checkout tries.
 * Transient ones (`charge_in_flight`, 503, offline, an unsafe URL) are not listed.
 */
const TERMINAL = new Set([
  "upgrade_unavailable",
  "seats_not_sold",
  "seats_exceed_new_tier",
  "not_an_upgrade",
  "not_a_teacher_plan",
  "subscription_not_active",
  "period_ending",
  "plan_change_pending",
  "seat_reduction_pending",
  "seat_charge_overdue",
  "invalid_seats",
  "invalid_extra_seats",
])

export function isTerminalRefusal(err: unknown): boolean {
  const code = billingErrorCode(err)
  return code !== null && TERMINAL.has(code)
}

/** A numeric fact the refusal carries (`extraSeats`, `inUse`, `capacity`), or null. */
function detailCount(err: unknown, key: "extraSeats" | "inUse" | "capacity"): number | null {
  if (!(err instanceof ApiError)) return null
  const v = (err.detail as Record<string, unknown> | undefined)?.[key]
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null
}

/** The cancel-and-resubscribe fallback `upgrade_unavailable` carries when the plan has a fixed amount. */
function wantsCancelAndResubscribe(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false
  return (err.detail as { next?: unknown } | undefined)?.next === "cancel_and_resubscribe"
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** Conflicts whose wording depends on facts in the refusal. */
function detailedConflict(code: string, err: unknown): string | null {
  if (code === "upgrade_unavailable" && wantsCancelAndResubscribe(err)) {
    return "Can't upgrade mid-period. Cancel at period end, then subscribe to the new plan."
  }
  if (code === "seats_not_sold") {
    const extra = detailCount(err, "extraSeats")
    return extra
      ? `That plan has no extra seats, and you hold ${extra}. Remove them first.`
      : "That plan has no extra seats. Remove yours first."
  }
  if (code === "seats_exceed_new_tier") {
    const inUse = detailCount(err, "inUse")
    const capacity = detailCount(err, "capacity")
    return inUse !== null && capacity !== null
      ? `That plan has ${plural(capacity, "seat", "seats")}; ${inUse} in use. Remove students first.`
      : null
  }
  return null
}

export function billingFailureMessage(err: unknown, action: string): string {
  const status = err instanceof ApiError ? err.status : -1
  if (status === 0) return "You're offline. Nothing was charged."
  if (status === 503) return "Payments are unavailable. Nothing was charged. Try again soon."
  if (status === 403) return "Only the person who pays can do this."
  if (status === 429) return "Too many attempts. Wait a minute."
  if (status === 409) {
    const code = billingErrorCode(err)
    if (code) {
      const specific = detailedConflict(code, err)
      if (specific) return specific
      if (CONFLICTS[code]) return CONFLICTS[code]
    }
  }
  // UD-11. `PlansView` shows the phone field in place of this line; any other caller still gets a
  // sentence that names the fix instead of "check the details".
  if (status === 422 && isCheckoutPhoneRequired(err)) return `${PHONE_CHECKOUT_HEADING}.`
  if (status === 422) {
    const code = billingErrorCode(err)
    if (code && INVALID[code]) return INVALID[code]
    return `Couldn't ${action}. Check the details.`
  }
  return `Couldn't ${action}. Nothing was charged. Try again.`
}

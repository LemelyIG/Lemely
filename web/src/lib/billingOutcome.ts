import { ApiError } from "@/lib/api"
import { PHONE_CHECKOUT_HEADING, isCheckoutPhoneRequired } from "@/lib/phone"

/*
 * What a payer is told when a billing write fails. Every billing write inserts its payment row
 * before calling Paymob (spec §6), so a failed request never charged anyone, and saying so is
 * the one thing a payer most needs to hear. Status-first: the backend's own messages are
 * written for client authors, not payers.
 *
 * Error bodies differ by phase (M11): Phase 03 sends `detail: {code, message}`, Phases 05/06
 * `detail: {error, message}`, Phase 02 a plain-string `detail`. `billingErrorCode` reads both
 * object shapes.
 */

export function billingErrorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null
  const d = err.detail as { code?: unknown; error?: unknown } | undefined
  if (!d || typeof d !== "object") return null
  if (typeof d.code === "string") return d.code
  return typeof d.error === "string" ? d.error : null
}

const CONFLICTS: Record<string, string> = {
  already_subscribed: "There's already an active plan on this account. Change it from the billing page instead.",
  no_saved_card: "There's no saved card for this. Buy a credit pack by card once and Lemely keeps the card for later charges.",
  seats_in_use:
    "More students hold seats than this would leave. Remove students first. A removed student's seat frees up at the end of the month.",
  seats_insufficient: "That plan has fewer seats than students you have seated. Remove students first, then change the plan.",
  seats_exceed_new_tier: "That plan has fewer seats than students you have seated. Remove students first, then change the plan.",
  charge_in_flight: "A payment for this is already being confirmed. Wait a minute, then check again.",
  not_an_upgrade: "That plan isn't an upgrade from your current one. Pick it from the plans page instead.",
  not_a_teacher_plan: "Extra seats are only for teacher plans.",
  subscription_not_active: "Your plan's last payment didn't go through, so it can't be changed until it's paid.",
  upgrade_unavailable: "This plan can't be upgraded mid-period right now. Your plan is unchanged and nothing was charged.",
  seat_reduction_unavailable: "Seats can't be reduced right now. Nothing has changed.",
  seat_reduction_locked: "You can change this reduction at your next renewal.",
  seats_changing: "Your seats were just changed. Check the count, then try again.",
  seats_over_limit: "That would take you past the most seats a plan can hold.",
  settings_changing: "These settings just changed. Reload and try again.",
  cap_below_pack_price: "The monthly limit is lower than the price of one pack. Raise the limit or pick a smaller pack.",
  plan_change_pending: "A plan change is already scheduled. It applies at the end of this period.",
  downgrade_unavailable:
    "This plan can't be scheduled as a downgrade right now. Your current plan is unchanged and nothing was charged. You can still cancel it from the billing page.",
  period_ending: "This period ends too soon to change now. Try again after the renewal.",
  seat_reduction_pending: "A seat reduction is already scheduled for the end of this period.",
  seat_charge_overdue: "The last seat charge hasn't been paid yet. Check the saved card, then try again.",
  managed_by_another_payer: "Someone else pays for this account, so only they can change it.",
  no_free_seat: "This teacher has no free seats. Ask them to add a seat.",
  invite_already_redeemed: "That invite has already been used. Ask for a new one.",
  invite_limit: "There are too many open invites. Revoke one first.",
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
    return "This plan can't be upgraded mid-period. Cancel at the end of the period and subscribe to the new plan."
  }
  if (code === "seats_not_sold") {
    const extra = detailCount(err, "extraSeats")
    return extra
      ? `That plan doesn't include extra seats, and you have ${plural(extra, "extra seat", "extra seats")}. Remove them first, then change the plan.`
      : "That plan doesn't include extra seats. Remove any extra seats first, then change the plan."
  }
  if (code === "seats_exceed_new_tier") {
    const inUse = detailCount(err, "inUse")
    const capacity = detailCount(err, "capacity")
    return inUse !== null && capacity !== null
      ? `That plan has ${plural(capacity, "seat", "seats")} and ${inUse} ${inUse === 1 ? "is" : "are"} in use. Remove students first, then change the plan.`
      : null
  }
  return null
}

export function billingFailureMessage(err: unknown, action: string): string {
  const status = err instanceof ApiError ? err.status : -1
  if (status === 0) return "You're offline. Nothing was charged. Try again when you're back online."
  if (status === 503) return "Payments are unavailable right now. Nothing was charged. Try again in a few minutes."
  if (status === 403) return "This account can't manage billing here. Only the person who pays can."
  if (status === 429) return "Too many attempts. Wait a minute and try again."
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
  if (status === 422) return `Couldn't ${action}. Check the details and try again.`
  return `Couldn't ${action}. Nothing was charged. Try again.`
}

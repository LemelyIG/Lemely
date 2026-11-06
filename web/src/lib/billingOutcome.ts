import { ApiError } from "@/lib/api"

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
  charge_in_flight: "A charge for this is already being confirmed. Wait a minute, then check again.",
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

export function billingFailureMessage(err: unknown, action: string): string {
  const status = err instanceof ApiError ? err.status : -1
  if (status === 0) return "You're offline. Nothing was charged. Try again when you're back online."
  if (status === 503) return "Payments are unavailable right now. Nothing was charged. Try again in a few minutes."
  if (status === 403) return "This account can't manage billing here. Only the person who pays can."
  if (status === 429) return "Too many attempts. Wait a minute and try again."
  if (status === 409) {
    const code = billingErrorCode(err)
    if (code && CONFLICTS[code]) return CONFLICTS[code]
  }
  if (status === 422) return `Couldn't ${action}. Check the details and try again.`
  return `Couldn't ${action}. Nothing was charged. Try again.`
}

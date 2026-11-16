import { describe, expect, it } from "vitest"
import { formatMoney } from "@/lib/billingFormat"
import { priceChangeNotice } from "@/lib/priceChange"
import type { BillingSummary, SubscriptionView, WirePendingTermsChange } from "@/lib/billingTypes"
import { fx } from "./support/billingFixtures"

/** Currency output uses a no-break space; build expectations the same way. */
const m = (minor: number) => formatMoney(minor, "EGP", "en-GB")
const change = (over: Partial<WirePendingTermsChange> = {}): WirePendingTermsChange => ({
  effectiveAt: "2026-11-30T00:00:00Z",
  firstRenewalAt: "2026-12-01T00:00:00Z",
  priceMinor: 27500,
  extraSeatPriceMinor: 0,
  includedSeats: 0,
  priceChanges: true,
  allowanceChange: null,
  includedSeatsChanges: false,
  seatAllowanceChanges: false,
  endsInsteadOfMoving: false,
  ...over,
})
const sub = (over: Partial<SubscriptionView> = {}): SubscriptionView => ({ ...fx.activeSub, ...over })
const summary = (over: Partial<BillingSummary> = {}): BillingSummary => ({ ...fx.summary, ...over })
const notice = (s: SubscriptionView, sum: BillingSummary = summary({ subscription: s }), audience: "student" | "teacher" = "student") =>
  priceChangeNotice({ summary: sum, audience }, "en-GB")

describe("price-change notice", () => {
  it("shows nothing without a pending change", () => {
    expect(notice(sub())).toBeNull()
  })

  it("says what changes and when: the move", () => {
    const n = notice(sub({ pendingTermsChange: change() }))!
    expect(n.variant).toBe("move")
    expect(n.heading).toBe(`Your plan changes on 1 Dec 2026: ${m(27500)} per month.`)
    expect(n.canCancel).toBe(true)
  })

  it("leaves the price out when only something else changes, and says which way the allowance goes", () => {
    const more = notice(sub({ pendingTermsChange: change({ priceChanges: false, allowanceChange: "more" }) }))!
    expect(more.heading).toBe("Your plan changes on 1 Dec 2026.")
    expect(more.details).toEqual(["You get a bigger usage allowance."])
    const less = notice(sub({ pendingTermsChange: change({ allowanceChange: "less" }) }))!
    expect(less.details).toEqual(["Your usage allowance gets smaller."])
  })

  it("never states an allowance size", () => {
    const n = notice(sub({ pendingTermsChange: change({ allowanceChange: "more", seatAllowanceChanges: true }) }))!
    expect(`${n.heading} ${n.details.join(" ")}`).not.toMatch(/\d{3,}\s*(units|credits)/i)
  })

  it("falls back to the period end, then to the next renewal, when the server has no renewal date", () => {
    expect(notice(sub({ pendingTermsChange: change({ firstRenewalAt: null }) }))!.heading).toContain("on 1 Dec 2026")
    expect(notice(sub({ currentPeriodEnd: null, pendingTermsChange: change({ firstRenewalAt: null }) }))!.heading).toBe(
      `Your plan changes at your next renewal: ${m(27500)} per month.`,
    )
  })

  it("says the plan ends instead of moving, and offers no cancel", () => {
    const n = notice(sub({ pendingTermsChange: change({ endsInsteadOfMoving: true }) }))!
    expect(n.variant).toBe("ends")
    expect(n.heading).toBe("Your plan ends on 1 Dec 2026. Subscribe again to keep it at the new price.")
    expect(n.details).toEqual([`New price: ${m(27500)} per month.`])
    expect(n.canCancel).toBe(false)
  })

  it("keeps explaining a plan the platform already scheduled to end", () => {
    const n = notice(sub({ cancelAtPeriodEnd: true, cancelReason: "plan_terms_changed", pendingTermsChange: null }))!
    expect(n.variant).toBe("ended")
    expect(n.heading).toBe("Your plan ends on 1 Dec 2026 because its price changed. Subscribe again to keep it.")
  })

  it("offers cancel only while the plan is not already ending", () => {
    expect(notice(sub({ cancelAtPeriodEnd: true, pendingTermsChange: change() }))!.canCancel).toBe(false)
  })

  it("tells a teacher how many students to remove, counting the extra seats they keep", () => {
    const teacher = sub({ extraSeats: 2, pendingTermsChange: change({ includedSeats: 10, includedSeatsChanges: true }) })
    const sum = summary({ subscription: teacher, seats: { capacity: 22, used: 17 } })
    const n = notice(teacher, sum, "teacher")!
    expect(n.seats).toEqual({ remove: 5, capacity: 12, before: "1 Dec 2026" })
    expect(n.details).toContain("Included seats: 10.")
  })

  it("counts a scheduled seat reduction as the capacity at renewal", () => {
    const teacher = sub({ extraSeats: 4, pendingExtraSeats: 0, pendingTermsChange: change({ includedSeats: 10, includedSeatsChanges: true }) })
    const n = notice(teacher, summary({ subscription: teacher, seats: { capacity: 14, used: 12 } }), "teacher")!
    expect(n.seats).toEqual({ remove: 2, capacity: 10, before: "1 Dec 2026" })
  })

  it("shows no seat count when the team fits, or for a student, or when seats do not change", () => {
    const fits = sub({ extraSeats: 0, pendingTermsChange: change({ includedSeats: 20, includedSeatsChanges: true }) })
    expect(notice(fits, summary({ subscription: fits, seats: { capacity: 20, used: 20 } }), "teacher")!.seats).toBeNull()
    const over = sub({ pendingTermsChange: change({ includedSeats: 5, includedSeatsChanges: true }) })
    expect(notice(over, summary({ subscription: over, seats: { capacity: 20, used: 18 } }), "student")!.seats).toBeNull()
    const same = sub({ pendingTermsChange: change({ includedSeats: 5, includedSeatsChanges: false }) })
    expect(notice(same, summary({ subscription: same, seats: { capacity: 20, used: 18 } }), "teacher")!.seats).toBeNull()
  })

  it("states a changed extra-seat price", () => {
    const teacher = sub({ tier: { ...fx.activeSub.tier, extraSeatPriceMinor: 3000 }, pendingTermsChange: change({ extraSeatPriceMinor: 3500 }) })
    expect(notice(teacher, summary({ subscription: teacher }), "teacher")!.details).toContain(`Extra seats cost ${m(3500)} each.`)
    const unchanged = sub({ tier: { ...fx.activeSub.tier, extraSeatPriceMinor: 3000 }, pendingTermsChange: change({ extraSeatPriceMinor: 3000 }) })
    expect(notice(unchanged, summary({ subscription: unchanged }), "teacher")!.details).toEqual([])
  })
})

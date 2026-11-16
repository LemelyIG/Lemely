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
  seatsToRemove: null,
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

  it("says nothing about a move once the payer has cancelled: the plan ends first", () => {
    expect(notice(sub({ cancelAtPeriodEnd: true, pendingTermsChange: change() }))).toBeNull()
    expect(notice(sub({ cancelAtPeriodEnd: true, pendingTermsChange: change({ endsInsteadOfMoving: true }) }))).toBeNull()
  })

  it("still explains a platform cancel even while the change is pending", () => {
    expect(notice(sub({ cancelAtPeriodEnd: true, cancelReason: "plan_terms_changed", pendingTermsChange: change() }))!.variant).toBe("ended")
  })

  it("words it for the child's plan when a parent is looking", () => {
    const s = sub({ pendingTermsChange: change() })
    const n = priceChangeNotice({ summary: summary({ subscription: s }), audience: "student", forChild: true }, "en-GB")!
    expect(n.heading.startsWith("This plan changes on")).toBe(true)
    const e = sub({ pendingTermsChange: change({ endsInsteadOfMoving: true }) })
    expect(priceChangeNotice({ summary: summary({ subscription: e }), audience: "student", forChild: true }, "en-GB")!.heading).toMatch(/^This plan ends on/)
  })

  it("prices the renewal with the extra seats the payer holds", () => {
    const t = sub({ extraSeats: 2, pendingTermsChange: change({ priceMinor: 100000, extraSeatPriceMinor: 3500 }) })
    const n = notice(t, summary({ subscription: t }), "teacher")!
    expect(n.heading).toBe(`Your plan changes on 1 Dec 2026: ${m(107000)} per month.`)
    expect(n.details).toContain(`Includes 2 extra seats at ${m(3500)} each.`)
  })

  it("tells a teacher how many students to remove, as the server counts them", () => {
    const teacher = sub({ extraSeats: 2, pendingTermsChange: change({ includedSeats: 10, includedSeatsChanges: true, seatsToRemove: 5 }) })
    const n = notice(teacher, summary({ subscription: teacher, seats: { capacity: 22, used: 17 } }), "teacher")!
    expect(n.seats).toEqual({ remove: 5, capacity: 12, before: "1 Dec 2026" })
  })

  it("does not count seats a teacher already removed (leaving seats still show in `used`)", () => {
    // Held 17, removed 5 (leaving until month end): 12 active, capacity 12. The server says 0.
    const teacher = sub({ extraSeats: 2, pendingTermsChange: change({ priceChanges: false, includedSeats: 10, includedSeatsChanges: true, seatsToRemove: 0 }) })
    expect(notice(teacher, summary({ subscription: teacher, seats: { capacity: 22, used: 17 } }), "teacher")!.seats).toBeNull()
  })

  it("shows no seat count for a student, or when the server has none", () => {
    const over = sub({ pendingTermsChange: change({ seatsToRemove: 4 }) })
    expect(notice(over, summary({ subscription: over }), "student")!.seats).toBeNull()
    const none = sub({ pendingTermsChange: change({ seatsToRemove: null }) })
    expect(notice(none, summary({ subscription: none }), "teacher")!.seats).toBeNull()
  })

  it("states a changed extra-seat price", () => {
    const teacher = sub({ tier: { ...fx.activeSub.tier, extraSeatPriceMinor: 3000 }, pendingTermsChange: change({ extraSeatPriceMinor: 3500 }) })
    expect(notice(teacher, summary({ subscription: teacher }), "teacher")!.details).toContain(`Extra seats cost ${m(3500)} each.`)
    const unchanged = sub({ tier: { ...fx.activeSub.tier, extraSeatPriceMinor: 3000 }, pendingTermsChange: change({ extraSeatPriceMinor: 3000 }) })
    expect(notice(unchanged, summary({ subscription: unchanged }), "teacher")!.details).toEqual([])
  })
})

import { describe, expect, it } from "vitest"
import {
  featureLines,
  toAutoTopup,
  toBillingSummary,
  toCatalogue,
  toEstimate,
  toHeldTier,
  toSavedCard,
  toUsageJob,
  toUsageMeter,
} from "@/lib/billingAdapters"
import type { WireBillingSummary, WirePlanTier, WireUsageMeter } from "@/lib/billingTypes"

const tier = (over: Partial<WirePlanTier> = {}): WirePlanTier => ({
  planTierId: "t1",
  code: "student_plus_m",
  name: "Student Plus",
  priceMinor: 25000,
  currency: "EGP",
  interval: "monthly",
  audience: "student",
  includedSeats: 0,
  extraSeatPriceMinor: 0,
  features: { "Mark past papers": true, hidden: false },
  ...over,
})
const meter: WireUsageMeter = {
  allowanceFraction: 0.63,
  allowanceResetsAt: "2026-12-01T00:00:00Z",
  creditsBalance: 700,
  creditLots: [{ remaining: 500, expiresAt: "2027-10-02T00:00:00Z" }],
  seats: [{ teacherMemberId: "m1", teacherUserId: "u9", fraction: null, resetsAt: null }],
  debtUnits: 0,
}

describe("billing adapters", () => {
  it("renames catalogue fields, maps intervals, keeps one audience and drops interval-less tiers", () => {
    const c = toCatalogue(
      {
        planTiers: [tier(), tier({ planTierId: "t2", audience: "teacher", includedSeats: 20, extraSeatPriceMinor: 3000 }), tier({ planTierId: "t3", interval: null })],
        creditPacks: [{ creditPackId: "p1", code: "pack_500", name: "500 credits", credits: 500, priceMinor: 15000, currency: "EGP" }],
      },
      "student",
    )
    expect(c.tiers).toEqual([
      { id: "t1", code: "student_plus_m", name: "Student Plus", audience: "student", interval: "month", priceMinor: 25000, currency: "EGP", features: ["Mark past papers"], includedSeats: null, extraSeatPriceMinor: null },
    ])
    expect(c.packs[0]).toEqual({ id: "p1", code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP" })
    expect(toCatalogue({ planTiers: [tier({ audience: "teacher", includedSeats: 20, extraSeatPriceMinor: 3000 })], creditPacks: [] }, "teacher").tiers[0]).toMatchObject({ includedSeats: 20, extraSeatPriceMinor: 3000 })
    expect(featureLines({ a: true, b: "x", c: false })).toEqual(["a"])
  })

  it("nests the flat usage meter", () => {
    expect(toUsageMeter(meter)).toEqual({
      allowance: { fraction: 0.63, resetsAt: "2026-12-01T00:00:00Z" },
      seats: [{ teacherMemberId: "m1", teacherUserId: "u9", fraction: null, resetsAt: null }],
      credits: { total: 700, buckets: [{ key: "0-2027-10-02T00:00:00Z", remaining: 500, expiresAt: "2027-10-02T00:00:00Z" }] },
      debtUnits: 0,
    })
    expect(toUsageMeter({ ...meter, allowanceFraction: null }).allowance).toBeNull()
  })

  it("builds the summary: tier from 02's PlanTierDTO, flat usage and credits nested into a meter", () => {
    const w: WireBillingSummary = {
      beneficiary: { userId: "u2", displayName: "Omar", audience: "student" },
      subscription: {
        subscriptionId: "sub1",
        status: "active",
        tier: tier(),
        currentPeriodStart: "2026-11-01T00:00:00Z",
        currentPeriodEnd: "2026-12-01T00:00:00Z",
        cancelAtPeriodEnd: false,
        pendingTier: null,
        graceUntil: null,
        extraSeats: 0,
        pendingExtraSeats: null,
      },
      canManage: false,
      managedByName: "Mona",
      savedCard: { cardId: "c", maskedPan: "•••• 1", brand: null },
      usage: { fraction: 0.63, resetsAt: "2026-12-01T00:00:00Z" },
      credits: { totalUnits: 700, expiring: [{ units: 500, expiresAt: "2027-10-02T00:00:00Z" }] },
      debtUnits: 12,
      seats: null,
    }
    const s = toBillingSummary(w)
    expect(s.canManage).toBe(false)
    expect(s.managedByName).toBe("Mona")
    expect(s.subscription).toMatchObject({ subscriptionId: "sub1", status: "active", tier: { id: "t1", interval: "month" }, pendingTier: null })
    expect(s.meter).toEqual({
      allowance: { fraction: 0.63, resetsAt: "2026-12-01T00:00:00Z" },
      seats: [],
      credits: { total: 700, buckets: [{ key: "0-2027-10-02T00:00:00Z", remaining: 500, expiresAt: "2027-10-02T00:00:00Z" }] },
      debtUnits: 12,
    })
    expect(s.savedCard?.brand).toBe("Card")
    expect(toBillingSummary({ ...w, subscription: null }).subscription).toBeNull()
    expect(toSavedCard(null)).toBeNull()
  })

  it("keeps a held legacy subscription (no interval) in the summary while the catalogue drops it", () => {
    const legacy = tier({ interval: null })
    const w = {
      beneficiary: { userId: "u2", displayName: "Omar", audience: "student" },
      subscription: {
        subscriptionId: "sub1",
        status: "active" as const,
        tier: legacy,
        currentPeriodStart: null,
        currentPeriodEnd: null,
        cancelAtPeriodEnd: false,
        pendingTier: tier({ planTierId: "t9", interval: "yearly" }),
        graceUntil: null,
        extraSeats: 0,
        pendingExtraSeats: null,
      },
      canManage: true,
      managedByName: null,
      savedCard: null,
      usage: { fraction: null, resetsAt: null },
      credits: { totalUnits: 0, expiring: [] },
      debtUnits: 0,
      seats: null,
    }
    const s = toBillingSummary(w)
    expect(s.subscription?.tier).toMatchObject({ id: "t1", interval: null, audience: "student" })
    expect(s.subscription?.pendingTier?.interval).toBe("year")
    expect(toCatalogue({ planTiers: [legacy], creditPacks: [] }, "student").tiers).toEqual([])
  })

  it("never relabels an unknown audience as student", () => {
    const odd = tier({ audience: "admin" })
    expect(toCatalogue({ planTiers: [odd], creditPacks: [] }, "student").tiers).toEqual([])
    expect(toCatalogue({ planTiers: [odd], creditPacks: [] }, "teacher").tiers).toEqual([])
    expect(toHeldTier(odd)).toMatchObject({ audience: null, includedSeats: null })
    expect(toHeldTier(tier({ interval: "weekly" as never })).interval).toBeNull()
    const base = {
      beneficiary: { userId: "u", displayName: null, audience: "guardian" },
      subscription: null,
      canManage: false,
      managedByName: null,
      savedCard: null,
      usage: { fraction: null, resetsAt: null },
      credits: { totalUnits: 0, expiring: [] },
      debtUnits: 0,
      seats: null,
    }
    expect(toBillingSummary(base).beneficiary.audience).toBeNull()
  })

  it("maps auto top-up, estimates and jobs", () => {
    expect(toAutoTopup({ beneficiaryId: "u2", enabled: false, thresholdUnits: null, creditPackId: null, savedCardId: null, monthlyCapMinor: null, spentThisMonthMinor: 0, currency: "", disabledReason: null }).currency).toBe("EGP")
    expect(toEstimate({ low: 3, high: 5, payer: "credits", percentLow: null, percentHigh: null, blockedReason: "nope" }).blockedReason).toBeNull()
    expect(toEstimate({ low: 3, high: 5, payer: "none", percentLow: null, percentHigh: null, blockedReason: "insufficient_credits" }).blockedReason).toBe("insufficient_credits")
    expect(
      toUsageJob({ jobId: "j", action: "regrade", status: "released", paidBy: "none", percentOfPlan: null, credits: null, debtCredits: null, estimatePercentOfPlan: [1, 2], estimateCredits: null, actorUserId: "u", createdAt: "x", settledAt: null }),
    ).toMatchObject({ action: "regrade", status: "released", paidBy: "none" })
  })
})

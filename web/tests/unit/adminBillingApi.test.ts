import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  request: vi.fn(),
}))

import { request } from "@/lib/api"
import { toAdminCatalogue } from "@/lib/billingAdapters"
import { adminBillingApi as api } from "@/lib/hooks/useAdminBillingApi"

const req = vi.mocked(request)
beforeEach(() => {
  req.mockReset()
  req.mockResolvedValue({})
})

const r = { reason: "because" }

describe("margin request", () => {
  it("sends the half-open window and the rate, and omits the rate when there is none", async () => {
    await api.margin("2026-10-01", "2026-11-05", "50")
    await api.margin("2026-10-01", "2026-11-05", null)
    await api.margin("2026-10-01", "2026-11-05")
    expect(req.mock.calls.map((c) => c[0])).toEqual([
      "/admin/billing/margin?from=2026-10-01T00%3A00%3A00Z&to=2026-11-06T00%3A00%3A00Z&egpPerUsd=50",
      "/admin/billing/margin?from=2026-10-01T00%3A00%3A00Z&to=2026-11-06T00%3A00%3A00Z",
      "/admin/billing/margin?from=2026-10-01T00%3A00%3A00Z&to=2026-11-06T00%3A00%3A00Z",
    ])
  })
})

describe("admin billing fetchers (plan 07; request() adds /api)", () => {
  it("hits every admin billing route with the right method", async () => {
    await api.catalogue()
    await api.createTier({ ...r } as never)
    await api.updateTier("t1", { ...r } as never)
    await api.syncTier("t1", r)
    await api.createPack({ ...r } as never)
    await api.updatePack("p1", { ...r } as never)
    await api.createRate({ ...r } as never)
    await api.createEstimator({ ...r } as never)
    await api.updateFreeAllowance({ audience: "student", units: 300, validDays: null, expectedVersion: 2, ...r })
    await api.searchCustomers("omar h")
    await api.customer("u1")
    await api.grant("u1", { units: 5, validDays: null, requestId: "rq1", ...r })
    await api.adjust("u1", { units: -5, requestId: "rq2", ...r })
    await api.forgiveDebt("u1", { units: null, ...r })
    await api.manualActivation("u1", { planTierId: "t1", periodDays: 30, ...r })
    await api.extend("s1", { days: 7, ...r })
    await api.cancelSubscription("s1", { when: "period_end", ...r })
    await api.refund("p1", { amountMinor: 100, ...r })
    await api.voidPayment("p1", r)
    await api.reconcile("p1", r)
    await api.payments("pending", "c 2")
    await api.problems()
    await api.margin("2026-10-01", "2026-11-30")
    await api.health()
    expect(req.mock.calls.map((c) => [c[0], (c[1] as RequestInit | undefined)?.method ?? "GET"])).toEqual([
      ["/admin/billing/catalogue", "GET"],
      ["/admin/billing/tiers", "POST"],
      ["/admin/billing/tiers/t1", "PUT"],
      ["/admin/billing/tiers/t1/sync", "POST"],
      ["/admin/billing/packs", "POST"],
      ["/admin/billing/packs/p1", "PUT"],
      ["/admin/billing/rates", "POST"],
      ["/admin/billing/estimators", "POST"],
      ["/admin/billing/free-allowances", "PUT"],
      ["/admin/billing/customers?q=omar%20h", "GET"],
      ["/admin/billing/customers/u1", "GET"],
      ["/admin/billing/customers/u1/grant", "POST"],
      ["/admin/billing/customers/u1/adjust", "POST"],
      ["/admin/billing/customers/u1/forgive-debt", "POST"],
      ["/admin/billing/customers/u1/manual-activation", "POST"],
      ["/admin/billing/subscriptions/s1/extend", "POST"],
      ["/admin/billing/subscriptions/s1/cancel", "POST"],
      ["/admin/billing/payments/p1/refund", "POST"],
      ["/admin/billing/payments/p1/void", "POST"],
      ["/admin/billing/payments/p1/reconcile", "POST"],
      ["/admin/billing/payments?status=pending&cursor=c+2", "GET"],
      ["/admin/billing/problems", "GET"],
      ["/admin/billing/margin?from=2026-10-01T00%3A00%3A00Z&to=2026-12-01T00%3A00%3A00Z", "GET"],
      ["/admin/billing/health", "GET"],
    ])
  })

  it("lists all payments when no status filter is set", async () => {
    await api.payments(null, null)
    expect(req.mock.calls[0][0]).toBe("/admin/billing/payments")
  })
})

describe("toAdminCatalogue", () => {
  it("maps intervals and features, nulls student seat fields, names drift and folds free allowances", () => {
    const c = toAdminCatalogue({
      planTiers: [
        { id: "t1", code: "s_m", name: "Student Plus", audience: "student", interval: "monthly", priceMinor: 25000, currency: "EGP", allowanceUnits: 4000, includedSeats: 0, seatAllowanceUnits: 0, extraSeatPriceMinor: 0, features: { "Mark past papers": true }, isActive: true, version: 3, termsVersion: 1, liveSubscriptionCount: 0, pendingMoves: 0, paymobPlanId: 77, paymobDrift: "in_sync" },
        { id: "t2", code: "t_m", name: "Teacher Pro", audience: "teacher", interval: "yearly", priceMinor: 900000, currency: "EGP", allowanceUnits: 9000, includedSeats: 20, seatAllowanceUnits: 300, extraSeatPriceMinor: 3000, features: {}, isActive: true, version: 1, termsVersion: 1, liveSubscriptionCount: 4, pendingMoves: 2, paymobPlanId: null, paymobDrift: "not_synced" },
      ],
      creditPacks: [],
      freeAllowances: [
        { audience: "student", creditPackId: "fs", units: 300, validDays: null, version: 2 },
        { audience: "teacher", creditPackId: "ft", units: 1000, validDays: 30, version: 3 },
      ],
      usageRates: [],
      usageEstimators: [],
      subscriptionAmountUpdatable: false,
      priceChangeNoticeDays: 45,
    })
    expect(c).toMatchObject({ subscriptionAmountUpdatable: false, priceChangeNoticeDays: 45 })
    expect(c.tiers[1]).toMatchObject({ version: 1, termsVersion: 1, liveSubscriptionCount: 4, pendingMoves: 2 })
    expect(c.tiers[0]).toMatchObject({ interval: "month", features: ["Mark past papers"], includedSeats: null, seatAllowanceUnits: null, extraSeatPriceMinor: null, drift: null })
    expect(c.tiers[1]).toMatchObject({ interval: "year", includedSeats: 20, seatAllowanceUnits: 300, extraSeatPriceMinor: 3000, drift: "Not synced to Paymob yet" })
    expect(c.freeAllowances).toEqual({
      studentSignupUnits: 300,
      teacherSignupUnits: 1000,
      studentSignupExpiryDays: null,
      teacherSignupExpiryDays: 30,
      studentVersion: 2,
      teacherVersion: 3,
    })
  })
})

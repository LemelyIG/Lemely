import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  request: vi.fn(),
}))

import { QueryClient } from "@tanstack/react-query"
import { ApiError, request } from "@/lib/api"
import {
  BILLING_SUCCESS_KEYS,
  billingApi,
  invalidateBilling,
  nextPaymentPoll,
  pollInterval,
  pollingExpired,
  schedulePollExpiry,
  startPollClock,
  syncPollClock, PAYMENT_POLL_LIMIT_MS,
  PAYMENT_POLL_MS,
} from "@/lib/hooks/useBillingApi"
import { usageApi } from "@/lib/hooks/useUsageApi"
import { billingErrorCode, billingFailureMessage, isTerminalRefusal } from "@/lib/billingOutcome"
import { billingPaths } from "@/lib/billingPaths"
import { formatBillingDate } from "@/lib/billingFormat"

const req = vi.mocked(request)

beforeEach(() => {
  req.mockReset()
  req.mockResolvedValue({})
})

const calls = () => req.mock.calls.map((c) => [c[0], (c[1] as RequestInit | undefined)?.method ?? "GET"])

describe("billing fetchers (paths without /api: request() adds it)", () => {
  it("hits every billing route with the right method", async () => {
    await billingApi.catalogue()
    await billingApi.summary(null)
    await billingApi.summary("child 1")
    await billingApi.startSubscriptionCheckout({ planTierId: "t1", beneficiaryId: null, extraSeats: 2 })
    await billingApi.startPackCheckout({ creditPackId: "p1", beneficiaryId: "c1" })
    await billingApi.payment("pay/1")
    await billingApi.upgradeQuote("s1", "t2")
    await billingApi.upgrade("s1", "t2")
    await billingApi.downgrade("s1", "t0")
    await billingApi.cancel("s1")
    await billingApi.receipts()
    await billingApi.autoTopup(null)
    await billingApi.autoTopup("c1")
    await billingApi.saveAutoTopup({ beneficiaryId: null, enabled: true, thresholdUnits: 100, creditPackId: "p1", savedCardId: "card1", monthlyCapMinor: 50000 })
    await billingApi.cards()
    await billingApi.seatQuote("s1", 3)
    await billingApi.addSeats("s1", 3)
    await billingApi.reduceSeats("s1", 1)
    await billingApi.publicCatalogue("teacher")
    expect(calls()).toEqual([
      ["/billing/catalogue", "GET"],
      ["/billing/summary", "GET"],
      ["/billing/summary?beneficiaryId=child%201", "GET"],
      ["/billing/subscriptions/checkout", "POST"],
      ["/billing/checkout/pack", "POST"],
      ["/billing/payments/pay%2F1", "GET"],
      ["/billing/subscriptions/s1/upgrade/quote", "POST"],
      ["/billing/subscriptions/s1/upgrade", "POST"],
      ["/billing/subscriptions/s1/downgrade", "POST"],
      ["/billing/subscriptions/s1/cancel", "POST"],
      ["/billing/receipts", "GET"],
      ["/billing/auto-topup", "GET"],
      ["/billing/auto-topup?beneficiaryId=c1", "GET"],
      ["/billing/auto-topup", "PUT"],
      ["/billing/cards", "GET"],
      ["/billing/subscriptions/s1/seats/quote", "POST"],
      ["/billing/subscriptions/s1/seats", "POST"],
      ["/billing/subscriptions/s1/seats/pending", "PUT"],
      ["/billing/public-catalogue?audience=teacher", "GET"],
    ])
  })

  it("sends the backend request bodies", async () => {
    await billingApi.upgrade("s1", "t2")
    await billingApi.addSeats("s1", 3)
    await billingApi.reduceSeats("s1", 1)
    const bodies = req.mock.calls.map((c) => JSON.parse(String((c[1] as RequestInit).body)))
    expect(bodies).toEqual([{ planTierId: "t2" }, { seats: 3 }, { extraSeats: 1 }])
  })
})

describe("usage fetchers", () => {
  it("posts the flat estimate body and pages history with a cursor", async () => {
    await usageApi.estimate({ action: "regrade", paperId: "p1" })
    await usageApi.meter()
    await usageApi.history(null)
    await usageApi.history("next 2")
    expect(calls()).toEqual([
      ["/usage/estimate", "POST"],
      ["/usage/meter", "GET"],
      ["/usage/history?limit=25", "GET"],
      ["/usage/history?limit=25&cursor=next+2", "GET"],
    ])
    expect(JSON.parse(String((req.mock.calls[0][1] as RequestInit).body))).toEqual({ action: "regrade", paperId: "p1" })
  })
})

describe("payment polling", () => {
  it("polls every 2s while confirming and stops at terminal states or after 3 minutes", () => {
    expect(PAYMENT_POLL_MS).toBe(2000)
    expect(PAYMENT_POLL_LIMIT_MS).toBe(180_000)
    expect(nextPaymentPoll(undefined, 0, 1000)).toBe(2000)
    expect(nextPaymentPoll("pending", 0, 1000)).toBe(2000)
    expect(nextPaymentPoll("created", 0, 179_999)).toBe(2000)
    expect(nextPaymentPoll("pending", 0, 180_000)).toBe(false)
    expect(nextPaymentPoll("paid", 0, 1000)).toBe(false)
    expect(nextPaymentPoll("failed", 0, 1000)).toBe(false)
  })

  it("stops polling when the fetch itself failed", () => {
    expect(nextPaymentPoll(undefined, 0, 1000, true)).toBe(false)
    expect(nextPaymentPoll("pending", 0, 1000, true)).toBe(false)
    expect(nextPaymentPoll("pending", 0, 1000, false)).toBe(2000)
  })

  it("reports expiry only for an unconfirmed payment past the limit, relative to its own start", () => {
    expect(pollingExpired("pending", 0, 179_999)).toBe(false)
    expect(pollingExpired("pending", 0, 180_000)).toBe(true)
    expect(pollingExpired("created", 500_000, 600_000)).toBe(false)
    expect(pollingExpired("paid", 0, 999_999)).toBe(false)
    expect(pollingExpired(undefined, 0, 999_999)).toBe(false)
  })
})

describe("payment poll clock (the logic usePaymentStatus delegates to)", () => {
  afterEach(() => vi.useRealTimers())

  it("returns interval false after a fetch error, 2s otherwise", () => {
    const clock = startPollClock("p1", 0)
    expect(pollInterval(clock, undefined, 1000, true)).toBe(false)
    expect(pollInterval(clock, "pending", 1000, true)).toBe(false)
    expect(pollInterval(clock, "pending", 1000, false)).toBe(2000)
  })

  it("resets the clock when the payment id changes and keeps it otherwise", () => {
    const first = startPollClock("p1", 1000)
    expect(syncPollClock(first, "p1", 5000)).toBe(first)
    const second = syncPollClock(first, "p2", 200_000)
    expect(second).toEqual({ id: "p2", startedAt: 200_000 })
    expect(pollInterval(first, "pending", 200_000, false)).toBe(false)
    expect(pollInterval(second, "pending", 200_000, false)).toBe(2000)
  })

  it("fires the expiry callback at the 3-minute limit, not before", () => {
    vi.useFakeTimers()
    vi.setSystemTime(0)
    const onExpire = vi.fn()
    schedulePollExpiry(startPollClock("p1", 0), "pending", Date.now(), onExpire)
    vi.advanceTimersByTime(PAYMENT_POLL_LIMIT_MS - 1)
    expect(onExpire).not.toHaveBeenCalled()
    vi.advanceTimersByTime(2)
    expect(onExpire).toHaveBeenCalledTimes(1)
    expect(pollingExpired("pending", 0, Date.now())).toBe(true)
  })

  it("measures the limit from the clock start and cancels on cleanup", () => {
    vi.useFakeTimers()
    vi.setSystemTime(100_000)
    const onExpire = vi.fn()
    const cancel = schedulePollExpiry(startPollClock("p1", 100_000), "created", Date.now(), onExpire)
    vi.advanceTimersByTime(PAYMENT_POLL_LIMIT_MS - 1)
    expect(onExpire).not.toHaveBeenCalled()
    cancel()
    vi.advanceTimersByTime(10)
    expect(onExpire).not.toHaveBeenCalled()
  })

  it("schedules nothing for a settled or unknown status", () => {
    vi.useFakeTimers()
    const onExpire = vi.fn()
    for (const status of ["paid", "failed", undefined] as const) {
      schedulePollExpiry(startPollClock("p1", 0), status, 0, onExpire)()
    }
    schedulePollExpiry(startPollClock("p1", 0), "paid", 0, onExpire)
    vi.advanceTimersByTime(PAYMENT_POLL_LIMIT_MS * 2)
    expect(onExpire).not.toHaveBeenCalled()
  })
})

describe("billing success invalidation", () => {
  it("refreshes billing data and the usage prefix (estimates, meter, history) together", () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, "invalidateQueries")
    invalidateBilling(qc)
    expect(spy.mock.calls.map((c) => c[0]?.queryKey)).toEqual([["billing"], ["usage"]])
    expect(BILLING_SUCCESS_KEYS).toEqual([["billing"], ["usage"]])
  })
})

describe("billing failure copy", () => {
  it("reads both backend error shapes and keeps unknown codes generic", () => {
    const errorShape = (error: string) => new ApiError(409, "409", { error, message: "x" })
    const codeShape = (code: string) => new ApiError(409, "409", { code, message: "x" })
    expect(billingErrorCode(errorShape("no_saved_card"))).toBe("no_saved_card")
    expect(billingErrorCode(codeShape("no_free_seat"))).toBe("no_free_seat")
    expect(billingErrorCode(new ApiError(403, "You can only buy for a linked child", "You can only buy for a linked child"))).toBeNull()
    expect(billingFailureMessage(errorShape("no_saved_card"), "upgrade")).toMatch(/saved card/)
    expect(billingFailureMessage(errorShape("seats_in_use"), "remove seats")).toMatch(/seat/)
    expect(billingFailureMessage(errorShape("seats_insufficient"), "downgrade")).toMatch(/seat/)
    expect(billingFailureMessage(errorShape("weird"), "upgrade")).toBe("Couldn't upgrade. Nothing was charged. Try again.")
  })

  it("words the refusals in few words, with the facts the backend sends", () => {
    const err = (error: string, extra: object = {}, status = 409) => new ApiError(status, String(status), { error, message: "x", ...extra })
    const say = (e: ApiError) => billingFailureMessage(e, "change your plan")
    expect(say(err("upgrade_unavailable", { next: "cancel_and_resubscribe" }))).toBe(
      "Can't upgrade mid-period. Cancel at period end, then subscribe to the new plan.",
    )
    expect(say(err("upgrade_unavailable"))).toBe("This plan can't be upgraded now. Nothing was charged.")
    expect(say(err("subscription_not_active"))).toBe("Your plan isn't active right now. Check billing, then try again.")
    expect(say(err("seat_reduction_locked"))).toBe("Reduction locked. You can change it at your next renewal.")
    expect(say(err("seats_not_sold", { extraSeats: 3 }))).toMatch(/you hold 3\b/)
    expect(say(err("seats_exceed_new_tier", { inUse: 5, capacity: 3 }))).toBe("That plan has 3 seats; 5 in use. Remove students first.")
    expect(say(err("seats_exceed_new_tier"))).toMatch(/fewer seats than your students/)
    for (const code of ["not_an_upgrade", "not_a_teacher_plan", "seat_reduction_unavailable", "settings_changing", "period_ending", "cap_below_pack_price", "charge_in_flight"]) {
      const text = say(err(code))
      expect(text, code).not.toMatch(/^Couldn't/)
      expect(text, code).not.toMatch(/[!—]/)
    }
    expect(say(err("charge_in_flight"))).toBe("A payment is already being confirmed. Wait a minute, then try again.")
  })

  it("maps the real seat-limit refusal: 422 invalid_seats, never a 409 code", () => {
    // `_plan_seats` raises MerchantChargeError("invalid_seats"), which `_CHARGE_STATUS` answers with 422.
    const real = new ApiError(422, "422", { error: "invalid_seats", message: "That would pass the most extra seats allowed" })
    expect(billingFailureMessage(real, "add seats")).toBe("That's over the extra-seat limit. Try fewer.")
    // The two void reasons are never error codes, so they get no special copy.
    for (const code of ["seats_over_limit", "seats_changing"]) {
      expect(billingFailureMessage(new ApiError(409, "409", { error: code, message: "x" }), "add seats")).toBe("Couldn't add seats. Nothing was charged. Try again.")
    }
  })

  it("maps the first checkout's seat refusal, 422 invalid_extra_seats, to the same short copy", () => {
    const real = new ApiError(422, "422", { error: "invalid_extra_seats", message: "extra_seats exceeds the maximum" })
    expect(billingFailureMessage(real, "start checkout")).toBe("This plan can't take that many extra seats. Try fewer.")
    expect(billingFailureMessage(real, "start checkout")).not.toContain("extra_seats")
    expect(isTerminalRefusal(real)).toBe(true)
  })

  it("tells a payer whose monthly limit is below the pack price to raise it", () => {
    const e = new ApiError(409, "409", { error: "cap_below_pack_price", message: "monthly_cap_minor < pack.price_minor" })
    expect(billingFailureMessage(e, "save auto top-up")).toBe("Your monthly limit is below the pack price. Raise it to keep auto top-up working.")
  })

  it("says when plan and seat changes open after an early-renewed period (409 period_not_started)", () => {
    const e = new ApiError(409, "409", { error: "period_not_started", message: "x", opensAt: "2026-12-01T00:00:00Z" })
    expect(billingFailureMessage(e, "add seats")).toBe(`Your next period is already paid. Plan and seat changes open on ${formatBillingDate("2026-12-01T00:00:00Z")}.`)
    // A refusal without a usable date still says something true, and never prints the field.
    const bare = new ApiError(409, "409", { error: "period_not_started", message: "x", opensAt: "soon" })
    expect(billingFailureMessage(bare, "add seats")).toBe("Your next period is already paid. Plan and seat changes open when it starts.")
    // Retrying cannot work until the period starts: the button stays off.
    expect(isTerminalRefusal(e)).toBe(true)
  })

  it("marks refusals that fail the same way again as terminal, and transient ones as not", () => {
    const e = (error: string, status = 409) => new ApiError(status, String(status), { error, message: "x" })
    for (const c of ["upgrade_unavailable", "seats_not_sold", "seats_exceed_new_tier", "not_an_upgrade", "subscription_not_active", "period_ending"]) {
      expect(isTerminalRefusal(e(c)), c).toBe(true)
    }
    expect(isTerminalRefusal(e("invalid_seats", 422))).toBe(true)
    for (const c of ["charge_in_flight", "payments_unavailable"]) expect(isTerminalRefusal(e(c, c === "payments_unavailable" ? 503 : 409)), c).toBe(false)
    expect(isTerminalRefusal(new ApiError(0, "x"))).toBe(false)
  })

  it("says nothing was charged when offline or when payments are down", () => {
    expect(billingFailureMessage(new ApiError(0, "x"), "buy credits")).toMatch(/offline/)
    expect(billingFailureMessage(new ApiError(503, "x"), "buy credits")).toMatch(/Payments are unavailable/)
    for (const s of [0, 403, 409, 422, 429, 500, 503]) {
      expect(billingFailureMessage(new ApiError(s, "x"), "pay")).not.toMatch(/[!—]/)
    }
  })
})

describe("billing paths", () => {
  it("builds per-role billing routes; a parent has no child usage history (M6)", () => {
    expect(billingPaths({ role: "student" }).plans).toBe("/student/billing/plans")
    expect(billingPaths({ role: "teacher" }).overview).toBe("/teacher/billing")
    expect(billingPaths({ role: "parent", childId: "c1" })).toEqual({
      overview: "/parent/children/c1/billing",
      plans: "/parent/children/c1/billing/plans",
      packs: "/parent/children/c1/billing/plans#packs",
      history: null,
      receipts: "/parent/billing/receipts",
    })
  })
})

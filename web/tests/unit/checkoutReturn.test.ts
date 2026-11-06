import { describe, expect, it, vi } from "vitest"
import {
  clampExtraSeats,
  defaultBillingPath,
  initialInterval,
  invalidateOnPaid,
  isSafeCheckoutUrl,
  packCheckoutRequest,
  rememberReturnTo,
  returnCopy,
  returnToFor,
  seatsIncludedLabel,
  startCheckoutRedirect,
  subscriptionCheckoutRequest,
  tiersForInterval,
} from "@/lib/checkoutReturn"
import type { PlanTier } from "@/lib/billingTypes"

function memoryStorage(): Storage {
  const m = new Map<string, string>()
  return {
    get length() {
      return m.size
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, v),
  }
}

describe("return path memory", () => {
  it("remembers a same-origin path per payment and falls back otherwise", () => {
    const s = memoryStorage()
    rememberReturnTo("p1", "/teacher/billing", s)
    expect(returnToFor("p1", "/", s)).toBe("/teacher/billing")
    expect(returnToFor("p2", "/student/billing", s)).toBe("/student/billing")
    rememberReturnTo("p3", "//evil.example", s)
    expect(returnToFor("p3", "/", s)).toBe("/")
    rememberReturnTo("p4", "https://evil.example", s)
    expect(returnToFor("p4", "/", s)).toBe("/")
  })

  it.each(["/\\evil.example", "/\t/evil.example", "/\n/evil.example", "/\r/evil.example", "//evil.example", "https://evil.example", "javascript:alert(1)", "data:text/html,x", ""])(
    "never returns the payer to %j",
    (bad) => {
      const s = memoryStorage()
      rememberReturnTo("px", bad, s)
      expect(returnToFor("px", "/student/billing", s)).toBe("/student/billing")
    },
  )

  it("keeps a same-origin path with a query and fragment", () => {
    const s = memoryStorage()
    rememberReturnTo("pq", "/parent/children/c1/billing?x=1#packs", s)
    expect(returnToFor("pq", "/", s)).toBe("/parent/children/c1/billing?x=1#packs")
  })

  it("defaults by role", () => {
    expect(defaultBillingPath("student")).toBe("/student/billing")
    expect(defaultBillingPath("teacher")).toBe("/teacher/billing")
    expect(defaultBillingPath("school_admin")).toBe("/teacher/billing")
    expect(defaultBillingPath("parent")).toBe("/parent")
    expect(defaultBillingPath(undefined)).toBe("/")
  })
})

describe("checkout redirect", () => {
  it("only follows https or same-origin checkout URLs", () => {
    expect(isSafeCheckoutUrl("https://eg.checkout.paymob.com/?publicKey=a&clientSecret=b")).toBe(true)
    expect(isSafeCheckoutUrl("/billing/return/p1")).toBe(true)
    expect(isSafeCheckoutUrl("//evil.example")).toBe(false)
    expect(isSafeCheckoutUrl("javascript:alert(1)")).toBe(false)
    expect(isSafeCheckoutUrl("http://eg.checkout.paymob.com")).toBe(false)
  })

  it.each([
    "/\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "/\r/evil.example",
    "//evil.example",
    "javascript:alert(1)",
    "data:text/html,<script>1</script>",
    "https:\\\\evil.example",
    "https://evil.example\n",
    "HTTPS://eg.checkout.paymob.com",
    "",
  ])("refuses the checkout URL %j", (bad) => {
    expect(isSafeCheckoutUrl(bad)).toBe(false)
  })

  it("remembers the return path, then navigates; refuses unsafe URLs", () => {
    const go = vi.fn()
    const store = memoryStorage()
    vi.stubGlobal("sessionStorage", store)
    expect(startCheckoutRedirect({ paymentId: "p9", checkoutUrl: "https://eg.checkout.paymob.com/x" }, "/student/billing", go)).toBe(true)
    expect(go).toHaveBeenCalledWith("https://eg.checkout.paymob.com/x")
    expect(store.getItem("lemely.billing.returnTo.p9")).toBe("/student/billing")
    expect(startCheckoutRedirect({ paymentId: "p10", checkoutUrl: "javascript:x" }, "/", go)).toBe(false)
    expect(go).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
  })
})

describe("returnCopy", () => {
  it("covers every phase with the pinned copy", () => {
    expect(returnCopy("confirming", "credit_pack", false).heading).toBe("Confirming your payment")
    expect(returnCopy("confirming", "credit_pack", true).heading).toBe("Still confirming")
    expect(returnCopy("paid", "credit_pack", false).heading).toBe("Credits added")
    expect(returnCopy("paid", "auto_topup", false).heading).toBe("Credits added")
    expect(returnCopy("paid", "subscription_first", false).heading).toBe("Your plan is active")
    expect(returnCopy("paid", "upgrade_proration", false).heading).toBe("Plan upgraded")
    expect(returnCopy("paid", "extra_seats", false).heading).toBe("Seats added")
    expect(returnCopy("paid", "subscription_renewal", false).heading).toBe("Renewal paid")
    expect(returnCopy("failed", "credit_pack", false).heading).toBe("Payment didn't go through")
    expect(returnCopy("mismatch", "credit_pack", false).body).toContain("You don't need to pay again.")
    expect(returnCopy("reversed", "credit_pack", false).heading).toBe("This payment was reversed")
  })
})

describe("paid return refreshes billing once per payment", () => {
  it("invalidates once for a paid payment and not again on repeats", () => {
    const invalidate = vi.fn()
    const settled = { current: null as string | null }
    expect(invalidateOnPaid(invalidate, settled, "A", "paid")).toBe(true)
    expect(invalidateOnPaid(invalidate, settled, "A", "paid")).toBe(false)
    expect(invalidateOnPaid(invalidate, settled, "A", "paid")).toBe(false)
    expect(invalidate).toHaveBeenCalledTimes(1)
    expect(settled.current).toBe("A")
  })

  it("invalidates for a second paid payment in the same mount", () => {
    const invalidate = vi.fn()
    const settled = { current: null as string | null }
    invalidateOnPaid(invalidate, settled, "A", "paid")
    invalidateOnPaid(invalidate, settled, "B", "paid")
    invalidateOnPaid(invalidate, settled, "B", "paid")
    expect(invalidate).toHaveBeenCalledTimes(2)
    expect(settled.current).toBe("B")
  })

  it("does nothing for an unpaid phase, and waits for the paid one", () => {
    const invalidate = vi.fn()
    const settled = { current: null as string | null }
    for (const phase of ["confirming", "failed", "mismatch", "reversed", null] as const) {
      expect(invalidateOnPaid(invalidate, settled, "A", phase)).toBe(false)
    }
    expect(invalidate).not.toHaveBeenCalled()
    expect(invalidateOnPaid(invalidate, settled, "A", "paid")).toBe(true)
    expect(invalidate).toHaveBeenCalledTimes(1)
  })
})

const tier = (over: Partial<PlanTier>): PlanTier => ({
  id: "t",
  code: "c",
  name: "n",
  audience: "student",
  interval: "month",
  priceMinor: 1,
  currency: "EGP",
  features: [],
  includedSeats: null,
  extraSeatPriceMinor: null,
  ...over,
})

describe("checkout request builders", () => {
  it("builds a student subscription request with no extra seats", () => {
    expect(subscriptionCheckoutRequest({ id: "t1" }, "student", null, 5)).toEqual({ planTierId: "t1", beneficiaryId: null, extraSeats: 0 })
  })

  it("builds a parent-for-child request with the child as beneficiary", () => {
    expect(subscriptionCheckoutRequest({ id: "t1" }, "student", "child-1", 0)).toEqual({ planTierId: "t1", beneficiaryId: "child-1", extraSeats: 0 })
    expect(packCheckoutRequest({ id: "p1" }, "child-1")).toEqual({ creditPackId: "p1", beneficiaryId: "child-1" })
    expect(packCheckoutRequest({ id: "p1" }, null)).toEqual({ creditPackId: "p1", beneficiaryId: null })
  })

  it("carries clamped extra seats for a teacher only", () => {
    expect(subscriptionCheckoutRequest({ id: "t5" }, "teacher", null, 12).extraSeats).toBe(12)
    expect(subscriptionCheckoutRequest({ id: "t5" }, "teacher", null, 999).extraSeats).toBe(200)
    expect(subscriptionCheckoutRequest({ id: "t5" }, "teacher", null, -3).extraSeats).toBe(0)
    expect(clampExtraSeats(Number.NaN)).toBe(0)
    expect(clampExtraSeats(4.9)).toBe(4)
  })

  it("posts the yearly tier's own id when the yearly tier is chosen", () => {
    const tiers = [
      tier({ id: "m2", interval: "month", priceMinor: 45000 }),
      tier({ id: "y1", interval: "year", priceMinor: 250000 }),
      tier({ id: "m1", interval: "month", priceMinor: 25000 }),
      tier({ id: "y2", interval: "year", priceMinor: 450000 }),
    ]
    expect(tiersForInterval(tiers, "month").map((t) => t.id)).toEqual(["m1", "m2"])
    const yearly = tiersForInterval(tiers, "year")
    expect(yearly.map((t) => t.id)).toEqual(["y1", "y2"])
    expect(subscriptionCheckoutRequest(yearly[0]!, "student", "child-1", 0)).toEqual({ planTierId: "y1", beneficiaryId: "child-1", extraSeats: 0 })
  })
})

describe("plan presentation helpers", () => {
  it("opens on the interval the payer already pays on", () => {
    expect(initialInterval("year")).toBe("year")
    expect(initialInterval("month")).toBe("month")
    expect(initialInterval(null)).toBe("month")
    expect(initialInterval(undefined)).toBe("month")
  })

  it("uses the singular for one seat", () => {
    expect(seatsIncludedLabel(1)).toBe("1 student seat included")
    expect(seatsIncludedLabel(20)).toBe("20 student seats included")
    expect(seatsIncludedLabel(0)).toBe("0 student seats included")
  })
})

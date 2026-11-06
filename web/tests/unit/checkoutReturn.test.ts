import { readFileSync } from "node:fs"
import { describe, expect, it, vi } from "vitest"
import {
  defaultBillingPath,
  isSafeCheckoutUrl,
  rememberReturnTo,
  returnCopy,
  returnToFor,
  shouldInvalidateBilling,
  startCheckoutRedirect,
} from "@/lib/checkoutReturn"

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

describe("billing cache refresh on a paid return", () => {
  it("fires once, and only for a paid payment", () => {
    expect(shouldInvalidateBilling("paid", false)).toBe(true)
    expect(shouldInvalidateBilling("paid", true)).toBe(false)
    expect(shouldInvalidateBilling("confirming", false)).toBe(false)
    expect(shouldInvalidateBilling("failed", false)).toBe(false)
    expect(shouldInvalidateBilling("mismatch", false)).toBe(false)
    expect(shouldInvalidateBilling("reversed", false)).toBe(false)
    expect(shouldInvalidateBilling(null, false)).toBe(false)
  })

  it("is wired into the return screen through invalidateBilling with a once-only guard", () => {
    const source = readFileSync(new URL("../../src/portals/billing/CheckoutReturn.tsx", import.meta.url), "utf8")
    expect(source).toContain("invalidateBilling(queryClient)")
    expect(source).toContain("shouldInvalidateBilling(phaseNow, invalidated.current)")
    expect(source).toContain("invalidated.current = true")
  })
})

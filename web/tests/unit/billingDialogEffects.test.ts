import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { billingFailureMessage } from "@/lib/billingOutcome"
import { fx } from "./support/billingFixtures"
import { fakeMutation, okQuery, renderStatic } from "./support/billingRender"

/*
 * `renderToStaticMarkup` never runs effects, so these tests run them: `useEffect` is replaced by
 * a function that calls its callback straight away. That is enough to see what the billing
 * dialogs ask the API for, and when they refresh billing, with spies on the hooks.
 */

const s = vi.hoisted(() => ({
  quote: null as unknown,
  upgrade: null as unknown,
  downgrade: null as unknown,
  payment: null as unknown,
  invalidated: [] as unknown[][],
}))

vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>()
  return { ...actual, useEffect: (fn: () => void) => void fn() }
})
vi.mock("@/lib/hooks/useBillingApi", () => ({
  useUpgradeQuote: () => s.quote,
  useUpgrade: () => s.upgrade,
  useDowngrade: () => s.downgrade,
  usePaymentStatus: () => s.payment,
  invalidateBilling: (...a: unknown[]) => void s.invalidated.push(a),
}))
vi.mock("@/components/ui/modal", () => ({
  Modal: (p: { open: boolean; children: unknown }) => (p.open ? h("div", { role: "dialog" }, p.children as never) : null),
}))

import { PaymentProgress } from "@/portals/billing/PaymentProgress"
import { PlanChangeDialog } from "@/portals/billing/PlanChangeDialog"

const up = { ...fx.studentMonthly, id: "t-up", name: "Student Max", priceMinor: 40000 }
const down = { ...fx.studentMonthly, id: "t-down", name: "Student Lite", priceMinor: 10000 }
const dialog = (tier = up, savedCard = fx.summary.savedCard) =>
  renderStatic(h(PlanChangeDialog, { open: true, onClose: () => undefined, subscription: fx.activeSub, tier, savedCard }))

beforeEach(() => {
  s.quote = fakeMutation()
  s.upgrade = fakeMutation()
  s.downgrade = fakeMutation()
  s.invalidated = []
  s.payment = Object.assign(okQuery(fx.payment), { pollingStopped: false })
})

describe("PaymentProgress", () => {
  it("refreshes billing once when the payment is paid, not while it is confirming", () => {
    renderStatic(h(PaymentProgress, { paymentId: "pay1" }))
    expect(s.invalidated).toHaveLength(0)
    s.payment = Object.assign(okQuery({ ...fx.payment, status: "paid", paidAt: "2026-11-05T09:01:00Z" }), { pollingStopped: false })
    renderStatic(h(PaymentProgress, { paymentId: "pay1" }))
    expect(s.invalidated).toHaveLength(1)
  })

  it("does not refresh for a failed payment", () => {
    s.payment = Object.assign(okQuery({ ...fx.payment, status: "failed" }), { pollingStopped: false })
    renderStatic(h(PaymentProgress, { paymentId: "pay1" }))
    expect(s.invalidated).toHaveLength(0)
  })
})

describe("PlanChangeDialog quote request", () => {
  const mutate = () => (s.quote as { mutate: ReturnType<typeof vi.fn> }).mutate

  it("quotes an upgrade when there is a saved card", () => {
    dialog()
    expect(mutate()).toHaveBeenCalledWith({ subscriptionId: "sub1", planTierId: "t-up" })
  })

  it("skips the quote when there is no saved card to charge", () => {
    dialog(up, null)
    expect(mutate()).not.toHaveBeenCalled()
  })

  it("never quotes a downgrade", () => {
    dialog(down)
    expect(mutate()).not.toHaveBeenCalled()
  })
})

describe("downgrade_unavailable", () => {
  it("tells the payer the change cannot be scheduled and that cancel still works", () => {
    const msg = billingFailureMessage(new ApiError(409, "x", { error: "downgrade_unavailable", message: "x" }), "change your plan")
    expect(msg).toMatch(/can't be scheduled/)
    expect(msg).toMatch(/cancel/)
    expect(msg).not.toMatch(/Try again/i)
  })
})

import { createElement, createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { billingPaths } from "@/lib/billingPaths"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, pendingQuery, renderAt, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({
  catalogue: null as unknown,
  summary: null as unknown,
  payment: null as unknown,
  subCheckout: null as unknown,
  packCheckout: null as unknown,
}))

vi.mock("@/lib/hooks/useBillingApi", () => ({
  useCatalogue: () => s.catalogue,
  useBillingSummary: () => s.summary,
  usePaymentStatus: () => s.payment,
  useStartSubscriptionCheckout: () => s.subCheckout,
  useStartPackCheckout: () => s.packCheckout,
  invalidateBilling: () => undefined,
}))
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ session: { role: "student" } }) }))
// `<Navigate>` redirects in an effect, which never runs in a static render, so it is replaced
// by a marker that carries its target.
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  Navigate: ({ to }: { to: string }) => createElement("p", null, `redirect:${to}`),
}))

import { BillingRedirect, CheckoutReturn } from "@/portals/billing/CheckoutReturn"
import { PlansView, type PlansViewProps } from "@/portals/billing/PlansView"

const paths = billingPaths({ role: "student" })
const view = (over: Partial<PlansViewProps> = {}) =>
  renderStatic(
    h(PlansView, {
      audience: "student",
      beneficiaryId: null,
      paths,
      currentTierId: null,
      hasLiveSubscription: false,
      canManage: true,
      managedByName: null,
      ...over,
    }),
  )

beforeEach(() => {
  s.catalogue = okQuery(fx.studentCatalogue)
  s.summary = okQuery(fx.summary)
  s.subCheckout = fakeMutation()
  s.packCheckout = fakeMutation()
  s.payment = Object.assign(okQuery(fx.payment), { pollingStopped: false })
})

describe("PlansView", () => {
  it("shows monthly tiers by default with price and interval, and packs under #packs", () => {
    const html = view()
    expect(html).toContain("Student Plus")
    expect(html).toMatch(/EGP\s250\.00/)
    expect(html).toContain("per month")
    expect(html).not.toMatch(/EGP\s2,500\.00/)
    expect(html).toContain('id="packs"')
    expect(html).toContain("500 credits")
    expect(html).toContain("Choose Student Plus")
  })

  it("never shows usage units (allowance sizes are hidden)", () => {
    expect(view()).not.toMatch(/\bunits\b/i)
  })

  it("marks the current plan and links other tiers to the plan-change dialog", () => {
    s.catalogue = okQuery({ ...fx.studentCatalogue, tiers: [fx.studentMonthly, { ...fx.studentMonthly, id: "t-s-m2", name: "Student Max" }] })
    const html = view({ currentTierId: "t-s-m", hasLiveSubscription: true })
    expect(html).toContain("Current plan")
    expect(html).toContain(`href="${paths.overview}?change=t-s-m2"`)
  })

  it("hides buy controls from a non-payer", () => {
    const html = view({ canManage: false, managedByName: "Mona" })
    expect(html).toContain("Mona manages billing for this account.")
    expect(html).not.toContain("Choose Student Plus")
  })


  it("shows teacher seats and the extra-seat field", () => {
    s.catalogue = okQuery(fx.teacherCatalogue)
    const html = view({ audience: "teacher", paths: billingPaths({ role: "teacher" }) })
    expect(html).toContain("20 student seats included")
    expect(html).toMatch(/Extra seats EGP\s30\.00 each per month/)
    expect(html).toContain('name="extraSeats"')
  })

  it("renders loading, error and empty states", () => {
    s.catalogue = pendingQuery()
    expect(view()).toContain('aria-label="Loading"')
    s.catalogue = errorQuery(new ApiError(500, "x"))
    expect(view()).toContain("load plans")
    s.catalogue = okQuery({ ...fx.studentCatalogue, tiers: [], packs: [] })
    expect(view()).toContain("No plans are on sale right now.")
  })

  it("shows a checkout failure as an alert that says nothing was charged", () => {
    s.packCheckout = fakeMutation({ isError: true, error: new ApiError(503, "x") })
    const html = view()
    expect(html).toContain('role="alert"')
    expect(html).toContain("Payments are unavailable right now. Nothing was charged.")
  })
})

describe("BillingRedirect", () => {
  it("sends a student from /billing to their billing page", () => {
    const html = renderAt(h(BillingRedirect), "/billing", "/billing")
    expect(html).toContain("redirect:/student/billing")
  })
})

describe("CheckoutReturn", () => {
  const at = () => renderAt(h(CheckoutReturn), "/billing/return/:paymentId", "/billing/return/pay1")

  it("announces confirming while pending", () => {
    const html = at()
    expect(html).toMatch(/role="status"/)
    expect(html).toContain("Confirming your payment")
  })

  it("offers a manual re-check once polling stops", () => {
    s.payment = Object.assign(okQuery(fx.payment), { pollingStopped: true })
    const html = at()
    expect(html).toContain("Still confirming")
    expect(html).toContain("Check again")
  })

  it("confirms a paid pack and links back to billing", () => {
    s.payment = Object.assign(okQuery({ ...fx.payment, status: "paid", paidAt: "2026-11-05T09:01:00Z" }), { pollingStopped: false })
    const html = at()
    expect(html).toContain("Credits added")
    expect(html).toContain('href="/student/billing"')
  })

  it("offers a retry to plans after a failure", () => {
    s.payment = Object.assign(okQuery({ ...fx.payment, status: "failed" }), { pollingStopped: false })
    expect(at()).toContain('href="/student/billing/plans"')
  })

  it("shows a load error with a retry", () => {
    s.payment = Object.assign(errorQuery(new ApiError(0, "x")), { pollingStopped: false })
    expect(at()).toContain("load this payment")
  })
})

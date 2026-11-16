// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { PaymentStatusView } from "@/lib/billingTypes"
import { okQuery } from "./support/billingRender"

/* The branches of `/billing/return/:paymentId`, rendered: heading, glyph, receipt row, reference, and where each link goes. */

const s = vi.hoisted(() => ({ payment: null as unknown, stored: new Map<string, string>() }))
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ session: { role: "teacher" } }) }))
vi.mock("@/lib/hooks/useBillingApi", () => ({
  usePaymentStatus: () => s.payment,
  invalidateBilling: () => undefined,
}))

import { CheckoutReturn } from "@/portals/billing/CheckoutReturn"

const base: PaymentStatusView = {
  paymentId: "0f3a9c1e-aaaa-bbbb-cccc-1234567890ab",
  status: "paid",
  purpose: "upgrade_proration",
  amountMinor: 7500,
  currency: "EGP",
  description: "Upgrade to Teacher Max",
  paidAt: "2026-11-16T09:00:00Z",
  creditedUnits: null,
  outcome: "applied",
  voidReason: null,
}
const show = (over: Partial<PaymentStatusView>, polling = false) => {
  s.payment = Object.assign(okQuery({ ...base, ...over }), { pollingStopped: polling })
  render(
    h(QueryClientProvider, { client: new QueryClient() },
      h(MemoryRouter, { initialEntries: [`/billing/return/${base.paymentId}`] },
        h(Routes, null, h(Route, { path: "/billing/return/:paymentId", element: h(CheckoutReturn) })))),
  )
}
const mark = () => document.querySelector("[data-mark]")?.getAttribute("data-mark")
const link = (name: string | RegExp) => screen.getByRole("link", { name }).getAttribute("href")

beforeEach(() => {
  s.stored = new Map()
  vi.stubGlobal("sessionStorage", { getItem: (k: string) => s.stored.get(k) ?? null, setItem: () => undefined })
})

describe("CheckoutReturn", () => {
  it("applied: the normal paid copy and a plain receipt row", () => {
    show({})
    expect(screen.getByRole("heading", { name: "Plan upgraded" })).toBeTruthy()
    expect(mark()).toBe("paid")
    expect(screen.getByText("Upgrade to Teacher Max")).toBeTruthy()
  })

  it("credited: its own glyph, short copy, and a receipt row that says what was paid for", () => {
    show({ outcome: "credited", creditedUnits: 900, voidReason: "plan_ended" })
    expect(screen.getByRole("heading", { name: "Added to your credits" })).toBeTruthy()
    expect(screen.getByText("Your plan ended first, so we added this to your credits.")).toBeTruthy()
    expect(mark()).toBe("credited")
    expect(screen.getByText("Paid for: Upgrade to Teacher Max")).toBeTruthy()
    expect(screen.queryByText(/Nothing else changed/)).toBeNull()
  })

  it("needs_attention: a calm glyph unlike confirming, the reference, a support link, no timeframe", () => {
    show({ outcome: "needs_attention", voidReason: "seats_over_limit", purpose: "extra_seats", description: "2 extra seats" })
    expect(screen.getByRole("heading", { name: "Payment received, we're handling it" })).toBeTruthy()
    expect(mark()).toBe("attention")
    expect(mark()).not.toBe("confirming")
    expect(screen.getByText("0f3a9c1e")).toBeTruthy()
    expect(link("Contact support")).toMatch(/^mailto:contact@lemelyig\.com\?subject=Payment%200f3a9c1e$/)
    expect(document.body.textContent).not.toMatch(/\b(hours?|days?|minutes?|within)\b/i)
    expect(screen.queryByText(/added|upgraded/i)).toBeNull()
  })

  it("extra seats with nothing remembered (a bank app opened a new tab) go back to the team page", () => {
    show({ status: "failed", outcome: null, purpose: "extra_seats", description: "2 extra seats", paidAt: null })
    expect(link("Try again")).toBe("/teacher/team")
    expect(link("Back to your team")).toBe("/teacher/team")
  })

  it("an upgrade that failed goes back to the plans page", () => {
    show({ status: "failed", outcome: null, paidAt: null })
    expect(link("Try again")).toBe("/teacher/billing/plans")
    expect(link("Back to billing")).toBe("/teacher/billing")
  })

  it("remembered paths still win", () => {
    s.stored.set(`lemely.billing.returnTo.${base.paymentId}`, "/teacher/team")
    show({ status: "failed", outcome: null, paidAt: null, purpose: "extra_seats" })
    expect(link("Back to your team")).toBe("/teacher/team")
  })

  it("confirming shows no support link and polls on", () => {
    show({ status: "pending", outcome: null, paidAt: null })
    expect(screen.getByRole("heading", { name: "Confirming your payment" })).toBeTruthy()
    expect(mark()).toBe("confirming")
    expect(screen.queryByText("Contact support")).toBeNull()
  })
})

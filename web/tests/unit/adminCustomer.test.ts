import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import type { AdminRefund } from "@/lib/billingTypes"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, renderAt, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({ search: null as unknown, customer: null as unknown, catalogue: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useCustomerSearch: () => s.search,
  useCustomer: () => s.customer,
  useAdminCatalogue: () => s.catalogue,
  useGrantCredits: () => fakeMutation(),
  useAdjustBalance: () => fakeMutation(),
  useForgiveDebt: () => fakeMutation(),
  useManualActivation: () => fakeMutation(),
  useExtendSubscription: () => fakeMutation(),
  useAdminCancelSubscription: () => fakeMutation(),
  useRefundPayment: () => fakeMutation(),
  useVoidPayment: () => fakeMutation(),
  useReconcilePayment: () => fakeMutation(),
}))

import { BillingLayout } from "@/portals/admin/screens/billing/BillingLayout"
import { CustomerDetail } from "@/portals/admin/screens/billing/CustomerDetail"
import { Customers } from "@/portals/admin/screens/billing/Customers"

beforeEach(() => {
  s.search = okQuery({ hits: [{ userId: "u2", displayName: "Omar Hassan", email: "omar@example.com", role: "student", matchedOn: "email" }] })
  s.customer = okQuery(fx.customer)
  s.catalogue = okQuery(fx.adminCatalogue)
})

const detail = () => renderAt(h(CustomerDetail), "/platform/billing/customers/:userId", "/platform/billing/customers/u2")
const refund = (over: Partial<AdminRefund>): AdminRefund => ({
  id: "r1", kind: "refund", status: "unknown", amountMinor: 25000, reason: "duplicate", adminUserId: "a1", clawedBackUnits: 0, createdAt: "2026-11-05T10:00:00Z", updatedAt: "2026-11-05T10:00:00Z", ...over,
})
const withRefunds = (refunds: AdminRefund[], over: object = {}) => {
  s.customer = okQuery({ ...fx.customer, payments: [{ ...fx.adminPayment, refunds, ...over }] })
}

describe("Customers", () => {
  it("links each hit to its detail page and says what matched", () => {
    const html = renderStatic(h(Customers), "/platform/billing?q=omar")
    expect(html).toContain('href="/platform/billing/customers/u2"')
    expect(html).toContain("omar@example.com")
    expect(html).toContain("Email")
  })

  it("asks for two characters instead of searching on fewer", () => {
    expect(renderStatic(h(Customers), "/platform/billing?q=o")).toContain("Type at least two characters.")
    expect(renderStatic(h(Customers), "/platform/billing")).toContain("Type at least two characters.")
  })

  it("says so when nothing matches and when the search is refused", () => {
    s.search = okQuery({ hits: [] })
    expect(renderStatic(h(Customers), "/platform/billing?q=zzz")).toContain("No customer matches that search.")
    s.search = errorQuery(new ApiError(403, "no", undefined))
    const html = renderStatic(h(Customers), "/platform/billing?q=zzz")
    expect(html).toContain("You can")
    expect(html).toContain("search customers")
    expect(html).not.toContain("Try again")
  })
})

describe("CustomerDetail", () => {
  it("shows subscription, balance, debt, grants, jobs and payments", () => {
    const html = detail()
    expect(html).toContain("Omar Hassan")
    expect(html).toContain("Student Plus")
    expect(html).toContain("1,500")
    expect(html).toContain("period_allowance")
    expect(html).toContain("Outside range")
    expect(html).toContain("0.009000")
    expect(html).toContain("PM-1")
  })

  it("offers every reasoned action, forgiving debt only when there is debt", () => {
    const html = detail()
    for (const label of ["Grant credits", "Adjust balance", "Forgive debt", "Activate manually", "Extend subscription", "Cancel subscription", "Refund", "Void"]) {
      expect(html).toContain(label)
    }
    s.customer = okQuery({ ...fx.customer, balance: { ...fx.customer.balance, outstandingDebt: 0 }, debts: [] })
    expect(detail()).not.toContain("Forgive debt")
  })

  it("shows parents for a student", () => {
    expect(detail()).toContain("mona@example.com")
  })

  it("keeps the name an h2 under the layout's h1 and the sections h3", () => {
    const html = detail()
    expect(html).toContain("<h2")
    expect(html).not.toMatch(/<h1/)
    expect(html).toMatch(/<h3[^>]*>Balance<\/h3>/)
  })

  it("lets only a complimentary plan be extended, and says why for a Paymob-billed one", () => {
    const html = detail()
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Extend subscription/)
    expect(html).toContain("Paymob bills this plan")
    const sub = { ...fx.customer.subscriptions[0], isManuallyActivated: true, paymobSubscriptionId: null }
    s.customer = okQuery({ ...fx.customer, subscriptions: [sub] })
    const manual = detail()
    expect(manual).not.toMatch(/<button[^>]*disabled=""[^>]*>Extend subscription/)
    expect(manual).not.toContain("Paymob bills this plan")
    expect(manual).toContain("Complimentary")
  })

  it("disables manual activation when no plan is on sale for the role", () => {
    s.catalogue = okQuery({ ...fx.adminCatalogue, tiers: [] })
    const html = detail()
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Activate manually/)
    expect(html).toContain("manual activation is unavailable")
  })

  it("says nothing has been refunded, voided or checked yet on a clean payment", () => {
    const html = detail()
    expect(html).not.toContain("outcome unknown")
    expect(html).not.toContain("Check with Paymob")
  })

  it("never calls an unknown refund a failure and offers the check, not another refund", () => {
    withRefunds([refund({ status: "unknown" })])
    const html = detail()
    expect(html).toContain("Refund of EGP")
    expect(html).toContain("outcome unknown")
    expect(html).toContain("may have gone through")
    expect(html).toContain("Check with Paymob")
    expect(html).not.toContain("was declined")
    expect(html).not.toContain("Refund pay1")
    expect(html).not.toContain("Void pay1")
  })

  it("shows a declined refund as declined, leaves the payment refundable, and shows what a success took back", () => {
    withRefunds([refund({ id: "r1", status: "failed" }), refund({ id: "r2", status: "succeeded", amountMinor: 5000, clawedBackUnits: 300 })], { status: "partially_refunded", refundedMinor: 5000 })
    const html = detail()
    expect(html).toContain("was declined")
    expect(html).toContain("Paymob refused it. The payment is unchanged.")
    expect(html).toContain("300 unspent units taken back")
    expect(html).toContain("Refund pay1")
    expect(html).not.toContain("Void pay1")
    expect(html).not.toContain("Check with Paymob")
  })

  it("is quiet about a settled payment: no refund or void controls", () => {
    withRefunds([refund({ status: "succeeded" })], { status: "refunded", refundedMinor: 25000 })
    const html = detail()
    expect(html).not.toContain("Refund pay1")
    expect(html).not.toContain("Check with Paymob")
  })

  it("says plainly when the admin cannot open billing and offers no retry", () => {
    s.customer = errorQuery(new ApiError(403, "no", undefined))
    const html = detail()
    expect(html).toContain("open billing customers")
    expect(html).not.toContain("Try again")
    expect(html).not.toContain("Error")
  })

  it("never shows a failed plans read as an empty one", () => {
    s.catalogue = errorQuery(new ApiError(500, "boom", undefined))
    const html = detail()
    expect(html).toContain("Couldn&#x27;t load plans. Reload this page.")
    expect(html).not.toContain("No plan is on sale")
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Activate manually/)
  })

  it("keeps the Customers pill active on a customer's page and off on the catalogue", () => {
    const at = (url: string) => renderAt(h(BillingLayout), "/platform/billing/*", url)
    const onCustomer = at("/platform/billing/customers/u2")
    expect(onCustomer).toMatch(/aria-current="true"[^>]*>Customers</)
    expect(onCustomer).not.toMatch(/aria-current[^>]*>Catalogue</)
    expect(at("/platform/billing")).toMatch(/aria-current="page"[^>]*>Customers</)
    const onCatalogue = at("/platform/billing/catalogue")
    expect(onCatalogue).toMatch(/aria-current="page"[^>]*>Catalogue</)
    expect(onCatalogue).not.toMatch(/aria-current[^>]*>Customers</)
  })
})

import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { billingPaths } from "@/lib/billingPaths"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import type { SubscriptionView, WirePendingTermsChange } from "@/lib/billingTypes"
import { fx } from "./support/billingFixtures"
import { fakeMutation, okQuery, renderStatic } from "./support/billingRender"

/*
 * The customer's side of a plan or pack change: the price-change banner on the billing page in
 * each of its variants, and the "credits last N months" line, read from the server in both the
 * signed-in plans page and the public pricing page.
 */

const s = vi.hoisted(() => ({ summary: null as unknown, ownMeter: null as unknown, catalogue: null as unknown, publicCatalogue: null as unknown }))
vi.mock("@/lib/hooks/useBillingApi", () => ({
  useBillingSummary: () => s.summary,
  useCatalogue: () => s.catalogue,
  usePublicCatalogue: () => s.publicCatalogue,
  useUpgradeQuote: () => fakeMutation(),
  useUpgrade: () => fakeMutation(),
  useDowngrade: () => fakeMutation(),
  useCancelSubscription: () => fakeMutation(),
  useStartSubscriptionCheckout: () => fakeMutation(),
  useStartPackCheckout: () => fakeMutation(),
  usePaymentStatus: () => okQuery(fx.payment),
  invalidateBilling: () => undefined,
}))
vi.mock("@/lib/hooks/useUsageApi", () => ({ useUsageMeter: () => s.ownMeter }))
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ session: { role: "student" } }) }))
vi.mock("@/portals/marketing", () => ({ MarketingFrame: (p: { children: unknown }) => h("main", null, p.children as never) }))

import { BillingOverview } from "@/portals/billing/BillingOverview"
import { PlansView } from "@/portals/billing/PlansView"
import { Pricing } from "@/portals/marketing/Pricing"

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
const withSub = (over: Partial<SubscriptionView>) => {
  const subscription = { ...fx.activeSub, ...over }
  s.summary = okQuery({ ...fx.summary, subscription })
}
const overview = (audience: "student" | "teacher" = "student") =>
  renderStatic(h(BillingOverview, { scope: { role: audience }, audience, beneficiaryId: null, heading: "Plan and billing" }), `/${audience}/billing`)
/** Static markup escapes apostrophes and Intl uses no-break spaces: compare on the words. */
const plain = (v: string) => v.replace(/\u00a0/g, " ")
const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/ /g, " ").replace(/\s+/g, " ")

beforeEach(() => {
  s.summary = okQuery(fx.summary)
  s.ownMeter = okQuery({ ...fx.meter, seats: [] })
  s.catalogue = okQuery(fx.studentCatalogue)
  s.publicCatalogue = okQuery({ audience: "student", creditValidityMonths: 12, tiers: [], packs: fx.studentCatalogue.packs })
})

describe("price-change banner on the billing page", () => {
  it("shows nothing when no change is pending", () => {
    expect(overview()).not.toContain("price-change-heading")
  })

  it("the move: new price and date, what changes, and the way to cancel at period end", () => {
    withSub({ pendingTermsChange: change({ allowanceChange: "less" }) })
    const html = overview()
    const t = text(html)
    expect(t).toContain(`Your plan changes on ${formatBillingDate("2026-12-01T00:00:00Z")}: ${plain(formatMoney(27500, "EGP"))} per month.`)
    expect(t).toContain("Your usage allowance gets smaller.")
    expect(t).toContain("Cancel at period end")
    expect(html).toContain('aria-labelledby="price-change-heading"')
  })

  it("the end: the plan ends instead of moving, with a way back to the plans", () => {
    withSub({ pendingTermsChange: change({ endsInsteadOfMoving: true }) })
    const html = overview()
    expect(text(html)).toContain(`Your plan ends on ${formatBillingDate("2026-12-01T00:00:00Z")}. Subscribe again to keep it at the new price.`)
    expect(html).toContain(`href="${billingPaths({ role: "student" }).plans}"`)
    expect(text(html)).not.toContain("Cancel at period end")
    // The plan card agrees with the banner.
    expect(text(html)).toContain(`Ends ${formatBillingDate("2026-12-01T00:00:00Z")}`)
    expect(text(html)).not.toContain("Renews")
  })

  it("seats to remove: a teacher with a team larger than the new plan", () => {
    const teacher = { ...fx.activeSub, extraSeats: 2, pendingTermsChange: change({ includedSeats: 10, includedSeatsChanges: true, seatsToRemove: 5 }) }
    s.summary = okQuery({ ...fx.summary, subscription: teacher, seats: { capacity: 22, used: 17 } })
    const t = text(overview("teacher"))
    expect(t).toContain(`Remove 5 students from your team before ${formatBillingDate("2026-12-01T00:00:00Z")}. The new plan has 12 seats.`)
    expect(t).toContain("Manage seats")
  })

  it("a person who does not pay gets no cancel link", () => {
    s.summary = okQuery({ ...fx.summary, canManage: false, managedByName: "Mona", subscription: { ...fx.activeSub, pendingTermsChange: change() } })
    expect(text(overview())).not.toContain("Cancel at period end")
  })
})

describe("credit validity comes from the server", () => {
  const plans = () =>
    renderStatic(
      h(PlansView, { audience: "student", beneficiaryId: null, paths: billingPaths({ role: "student" }), currentTierId: null, hasLiveSubscription: false, canManage: true, managedByName: null }),
    )

  it("the plans page says 6 months when the server says 6", () => {
    s.catalogue = okQuery({ ...fx.studentCatalogue, creditValidityMonths: 6 })
    const t = text(plans())
    expect(t).toContain("They last 6 months from purchase.")
    expect(t).not.toContain("12 months")
  })

  it("the public pricing page says 6 months when the server says 6, and 1 month in the singular", () => {
    s.publicCatalogue = okQuery({ audience: "student", creditValidityMonths: 6, tiers: [], packs: fx.studentCatalogue.packs })
    expect(text(renderStatic(h(Pricing), "/pricing"))).toContain("Credits last 6 months from purchase.")
    s.publicCatalogue = okQuery({ audience: "student", creditValidityMonths: 1, tiers: [], packs: fx.studentCatalogue.packs })
    expect(text(renderStatic(h(Pricing), "/pricing"))).toContain("Credits last 1 month from purchase.")
  })
})

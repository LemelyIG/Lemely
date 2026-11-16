import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { formatBillingDate } from "@/lib/billingFormat"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({
  summary: null as unknown,
  ownMeter: null as unknown,
  catalogue: null as unknown,
  quote: null as unknown,
  upgrade: null as unknown,
  downgrade: null as unknown,
  cancel: null as unknown,
  payment: null as unknown,
  meterCalls: 0,
}))

vi.mock("@/lib/hooks/useBillingApi", () => ({
  useBillingSummary: () => s.summary,
  useCatalogue: () => s.catalogue,
  useUpgradeQuote: () => s.quote,
  useUpgrade: () => s.upgrade,
  useDowngrade: () => s.downgrade,
  useCancelSubscription: () => s.cancel,
  usePaymentStatus: () => s.payment,
  invalidateBilling: () => undefined,
}))
vi.mock("@/lib/hooks/useUsageApi", () => ({
  useUsageMeter: () => {
    s.meterCalls += 1
    return s.ownMeter
  },
}))
vi.mock("@/components/ui/modal", () => ({
  Modal: (p: { open: boolean; title: unknown; children: unknown; footer?: unknown; dismissible?: boolean }) =>
    p.open
      ? h(
          "div",
          { role: "dialog", "data-dismissible": String(p.dismissible ?? true) },
          h("h2", null, p.title as never),
          p.children as never,
          p.footer as never,
        )
      : null,
}))

import { BillingOverview, nextPinned } from "@/portals/billing/BillingOverview"
import { CancelPlanDialog } from "@/portals/billing/CancelPlanDialog"
import { PlanChangeDialog } from "@/portals/billing/PlanChangeDialog"

const overview = (over: Partial<Parameters<typeof BillingOverview>[0]> = {}, path = "/student/billing") =>
  renderStatic(
    h(BillingOverview, { scope: { role: "student" }, audience: "student", beneficiaryId: null, heading: "Plan and billing", ...over }),
    path,
  )

const wireSub = { ...fx.activeSub, id: "sub1", beneficiaryUserId: "u2", isPayer: true, planTierId: "t-s-m", planCode: "x", planName: "Student Plus", pendingPlanTierId: null }

beforeEach(() => {
  s.summary = okQuery(fx.summary)
  s.ownMeter = okQuery({ ...fx.meter, seats: [{ teacherMemberId: "m1", teacherUserId: "u9", fraction: 0.4, resetsAt: "2026-12-01T00:00:00Z" }] })
  s.catalogue = okQuery(fx.studentCatalogue)
  s.quote = fakeMutation()
  s.upgrade = fakeMutation()
  s.downgrade = fakeMutation()
  s.cancel = fakeMutation()
  s.payment = Object.assign(okQuery(fx.payment), { pollingStopped: false })
  s.meterCalls = 0
})

describe("BillingOverview", () => {
  it("shows an active plan with renewal date, meters and payer actions", () => {
    const html = overview()
    expect(html).toContain("Student Plus")
    expect(html).toMatch(/EGP\s250\.00/)
    expect(html).toContain("Renews")
    expect(html).toContain("Usage 63%")
    expect(html).toContain("Seat from your teacher: 40% used")
    expect(html).toContain("Change plan")
    expect(html).toContain("Cancel plan")
    expect(html).toContain('href="/student/billing/history"')
    expect(html).toContain('href="/student/billing/receipts"')
  })

  it("explains a credits-only account", () => {
    s.summary = okQuery({ ...fx.summary, subscription: null })
    const html = overview()
    expect(html).toContain("No plan")
    expect(html).toContain('href="/student/billing/plans"')
  })

  it("shows waiting, ending, scheduled-change and past-due states", () => {
    s.summary = okQuery({ ...fx.summary, subscription: { ...fx.activeSub, status: "pending_first_payment" } })
    expect(overview()).toContain("Waiting for the first payment to confirm.")
    s.summary = okQuery({ ...fx.summary, subscription: { ...fx.activeSub, cancelAtPeriodEnd: true } })
    const ending = overview()
    expect(ending).toContain("Usage comes from credits after that.")
    expect(ending).not.toContain("Cancel plan")
    s.summary = okQuery({ ...fx.summary, subscription: { ...fx.activeSub, pendingTier: { ...fx.studentMonthly, name: "Student Lite" } } })
    expect(overview()).toContain("Changes to Student Lite on")
    s.summary = okQuery({ ...fx.summary, subscription: { ...fx.activeSub, status: "past_due", graceUntil: "2026-11-08T00:00:00Z" } })
    expect(overview()).toMatch(/role="status"[^>]*>.*renewal didn/)
  })

  it("is read-only for a non-payer and hides receipts", () => {
    s.summary = okQuery({ ...fx.summary, canManage: false, managedByName: "Mona" })
    const html = overview()
    expect(html).toContain("Mona manages this plan.")
    expect(html).not.toContain("Cancel plan")
    expect(html).not.toContain("/receipts")
  })

  it("puts the debt notice above the plan", () => {
    s.summary = okQuery({ ...fx.summary, meter: { ...fx.meter, debtUnits: 12 } })
    const html = overview()
    expect(html.indexOf("12 credits more")).toBeLessThan(html.indexOf("Student Plus"))
  })

  it("shows teacher seats from the summary with a link to manage them", () => {
    s.summary = okQuery({
      ...fx.summary,
      beneficiary: { ...fx.summary.beneficiary, audience: "teacher" },
      subscription: { ...fx.activeSub, tier: fx.teacherMonthly, extraSeats: 2 },
      seats: { capacity: 22, used: 5 },
    })
    s.catalogue = okQuery(fx.teacherCatalogue)
    const html = overview({ scope: { role: "teacher" }, audience: "teacher" }, "/teacher/billing")
    expect(html).toContain("5 of 22 seats used")
    expect(html).toContain("20 included, 2 extra")
    expect(html).toContain('href="/teacher/team"')
  })

  it("has no usage-history link for a parent and skips own seat meters for a child", () => {
    const html = overview({ scope: { role: "parent", childId: "c1" }, beneficiaryId: "c1" }, "/parent/children/c1/billing")
    expect(html).not.toContain("Usage history")
    expect(html).not.toContain("Seat from your teacher")
  })

  it("renders loading and error states", () => {
    s.summary = pendingQuery()
    expect(overview()).toContain('aria-label="Loading"')
    s.summary = errorQuery(new ApiError(500, "x"))
    expect(overview()).toContain("load your billing")
  })

  it("shows the past-due panel when no grace date is known", () => {
    s.summary = okQuery({ ...fx.summary, subscription: { ...fx.activeSub, status: "past_due", graceUntil: null } })
    const html = overview()
    expect(html).toMatch(/role="status"[^>]*>.*renewal didn/)
    expect(html).not.toMatch(/keeps working until/)
  })

  it("offers no actions and no change dialog while the first payment is pending", () => {
    s.summary = okQuery({ ...fx.summary, subscription: { ...fx.activeSub, status: "pending_first_payment" } })
    s.catalogue = okQuery({ ...fx.studentCatalogue, tiers: [fx.studentMonthly, { ...fx.studentMonthly, id: "t-up", name: "Student Max", priceMinor: 40000 }] })
    const html = overview({}, "/student/billing?change=t-up")
    expect(html).not.toContain("Change plan")
    expect(html).not.toContain("See plans")
    expect(html).not.toContain("Cancel plan")
    expect(html).not.toContain('role="dialog"')
  })

  it("hides Manage seats from a teacher who does not pay", () => {
    s.summary = okQuery({
      ...fx.summary,
      canManage: false,
      managedByName: "School",
      beneficiary: { ...fx.summary.beneficiary, audience: "teacher" },
      subscription: { ...fx.activeSub, tier: fx.teacherMonthly, extraSeats: 2 },
      seats: { capacity: 22, used: 5 },
    })
    s.catalogue = okQuery(fx.teacherCatalogue)
    const html = overview({ scope: { role: "teacher" }, audience: "teacher" }, "/teacher/billing")
    expect(html).toContain("5 of 22 seats used")
    expect(html).not.toContain("Manage seats")
    expect(html).not.toContain('href="/teacher/team"')
  })

  it("names the child in the load failure when a parent views a child", () => {
    s.summary = errorQuery(new ApiError(500, "x"))
    const child = { scope: { role: "parent", childId: "c1" } as const, beneficiaryId: "c1" }
    expect(overview({ ...child }, "/parent/children/c1/billing")).toContain("load this child")
    const named = overview({ ...child, beneficiaryName: "Omar" }, "/parent/children/c1/billing")
    expect(named).toMatch(/load Omar(&#x27;|')s billing/)
    expect(named).not.toContain("your billing")
    expect(overview()).toContain("load your billing")
  })

  it("keeps Try again for network and server failures but not for 403 or 404", () => {
    for (const status of [0, 500, 503]) {
      s.summary = errorQuery(new ApiError(status, "x"))
      expect(overview(), `status ${status}`).toContain("Try again")
    }
    for (const status of [403, 404]) {
      s.summary = errorQuery(new ApiError(status, "x"))
      const html = overview()
      expect(html, `status ${status}`).toContain("load your billing")
      expect(html, `status ${status}`).not.toContain("Try again")
    }
  })

  it("reads the caller's own seat meters only for a signed-in beneficiary", () => {
    overview({ scope: { role: "parent", childId: "c1" }, beneficiaryId: "c1" }, "/parent/children/c1/billing")
    expect(s.meterCalls).toBe(0)
    overview()
    expect(s.meterCalls).toBeGreaterThan(0)
  })

  it("opens the plan-change dialog from ?change=", () => {
    s.catalogue = okQuery({ ...fx.studentCatalogue, tiers: [fx.studentMonthly, { ...fx.studentMonthly, id: "t-up", name: "Student Max", priceMinor: 40000 }] })
    expect(overview({}, "/student/billing?change=t-up")).toContain('role="dialog"')
  })
})

describe("nextPinned", () => {
  const plus = fx.activeSub
  const upgraded = { ...fx.activeSub, tier: { ...fx.studentMonthly, id: "t-up" } }

  it("opens for a tier that is not the current plan and closes with no tier", () => {
    expect(nextPinned(null, "t-up", plus)).toEqual({ tierId: "t-up", subscription: plus })
    expect(nextPinned(null, "t-s-m", plus)).toBeNull()
    expect(nextPinned(null, null, plus)).toBeNull()
    expect(nextPinned({ tierId: "t-up", subscription: plus }, null, plus)).toBeNull()
  })

  it("stays open, on the original subscription, after a paid upgrade makes the target current", () => {
    const pinned = nextPinned(null, "t-up", plus)
    const after = nextPinned(pinned, "t-up", upgraded)
    expect(after).toBe(pinned)
    expect(after?.subscription.tier.id).toBe("t-s-m")
    // without the pin the same inputs would close the dialog
    expect(nextPinned(null, "t-up", upgraded)).toBeNull()
  })

  it("switches to a different tier named in the URL", () => {
    const pinned = nextPinned(null, "t-up", plus)
    expect(nextPinned(pinned, "t-down", plus)?.tierId).toBe("t-down")
  })
})

describe("PlanChangeDialog", () => {
  const up = { ...fx.studentMonthly, id: "t-up", name: "Student Max", priceMinor: 40000 }
  const down = { ...fx.studentMonthly, id: "t-down", name: "Student Lite", priceMinor: 10000 }
  const dialog = (tier = up, savedCard = fx.summary.savedCard) =>
    renderStatic(h(PlanChangeDialog, { open: true, onClose: () => undefined, subscription: fx.activeSub, tier, savedCard, returnTo: "/teacher/billing" }))

  it("announces quoting an upgrade", () => {
    s.quote = fakeMutation({ isPending: true })
    expect(dialog()).toContain("Working out the price")
  })

  it("prices an upgrade and offers the saved card on Paymob's page", () => {
    s.quote = fakeMutation({ isSuccess: true, data: { amountMinor: 7500, currency: "EGP", allowanceUnits: 900, periodEnd: "2026-12-01T00:00:00Z" } })
    const html = dialog()
    expect(html).toMatch(/Continue to payment \(EGP\s75\.00\)/)
    expect(html).toContain("confirm it with your bank on the next page")
    expect(html).toContain("Mastercard")
    expect(html).not.toMatch(/upgraded|Upgraded/)
  })

  it("still offers payment with no saved card: the card is typed on Paymob's page", () => {
    s.quote = fakeMutation({ isSuccess: true, data: { amountMinor: 7500, currency: "EGP", allowanceUnits: 900, periodEnd: "2026-12-01T00:00:00Z" } })
    const html = dialog(up, null)
    expect(html).toMatch(/Continue to payment/)
    expect(html).not.toContain("saved card")
  })

  it("schedules a downgrade with no quote and no charge", () => {
    const html = dialog(down)
    expect(html).toContain("nothing is charged now")
    expect(html).toContain("Schedule the change")
  })

  it("holds the loading state on the way to checkout and reports a scheduled downgrade", () => {
    s.upgrade = fakeMutation({ isSuccess: true, data: { paymentId: "pay1", checkoutUrl: "https://eg.checkout.paymob.com/?x=1" } })
    expect(dialog()).toContain("Taking you to the payment page")
    expect(dialog()).toContain('data-dismissible="false"')
    s.upgrade = fakeMutation()
    s.downgrade = fakeMutation({ isSuccess: true, data: { ...wireSub, pendingPlanTierId: "t-down" } })
    expect(dialog(down)).toMatch(/role="status"[^>]*>Scheduled\. Student Lite starts on/)
  })

  it("shows the confirm step on a fresh open, ignoring results made for another tier", () => {
    const other = { subscriptionId: "sub1", planTierId: "t-other" }
    s.downgrade = Object.assign(
      fakeMutation({ isSuccess: true, data: { ...wireSub, pendingPlanTierId: "t-other" } }),
      { variables: other },
    )
    const html = dialog(down)
    expect(html).not.toContain("Scheduled.")
    expect(html).toContain("Schedule the change")
    s.downgrade = Object.assign(fakeMutation({ isError: true, error: new ApiError(500, "x") }), { variables: other })
    expect(dialog(down)).not.toContain("Couldn")
    // the same tier's own result still shows
    s.downgrade = Object.assign(
      fakeMutation({ isSuccess: true, data: { ...wireSub, pendingPlanTierId: "t-down" } }),
      { variables: { subscriptionId: "sub1", planTierId: "t-down" } },
    )
    expect(dialog(down)).toMatch(/role="status"[^>]*>Scheduled\. Student Lite starts on/)
  })

  it("cannot be dismissed while a charge or schedule is in flight", () => {
    expect(dialog()).toContain('data-dismissible="true"')
    s.upgrade = fakeMutation({ isPending: true })
    expect(dialog()).toContain('data-dismissible="false"')
    s.upgrade = fakeMutation()
    s.downgrade = fakeMutation({ isPending: true })
    expect(dialog(down)).toContain('data-dismissible="false"')
  })

  it("explains a downgrade that cannot be scheduled, without a retry", () => {
    s.downgrade = fakeMutation({ isError: true, error: new ApiError(409, "x", { error: "downgrade_unavailable", message: "x" }) })
    const html = dialog(down)
    expect(html).toContain('role="alert"')
    expect(html).toContain("can&#x27;t be scheduled as a downgrade")
    expect(html).toContain("still cancel it")
    expect(html).not.toContain("Try again")
  })

  it("removes the confirm button once the downgrade is unavailable, but keeps it for a seats conflict", () => {
    s.downgrade = fakeMutation({ isError: true, error: new ApiError(409, "x", { error: "downgrade_unavailable", message: "x" }) })
    expect(dialog(down)).not.toContain("Schedule the change")
    s.downgrade = fakeMutation({ isError: true, error: new ApiError(409, "x", { error: "seats_insufficient", message: "x" }) })
    expect(dialog(down)).toContain("Schedule the change")
  })

  it("shows a seats conflict as an alert", () => {
    s.downgrade = fakeMutation({ isError: true, error: new ApiError(409, "x", { error: "seats_insufficient", message: "x" }) })
    const html = dialog(down)
    expect(html).toContain('role="alert"')
    expect(html).toContain("fewer seats than students")
  })
})

describe("CancelPlanDialog", () => {
  it("states what happens at period end and confirms after success", () => {
    const render = () =>
      renderStatic(h(CancelPlanDialog, { open: true, onClose: () => undefined, subscription: fx.activeSub, audience: "teacher" }))
    const html = render()
    expect(html).toContain("Your plan stays active until")
    expect(html).toContain("Seats stop getting monthly allowances")
    expect(html).toContain("Cancel at period end")
    s.cancel = fakeMutation({ isSuccess: true, data: { ...wireSub, cancelAtPeriodEnd: true } })
    expect(render()).toMatch(/Cancelled\. Your plan ends on/)
  })

  it("tells a past-due plan its grace date, not the period end", () => {
    const pastDue = { ...fx.activeSub, status: "past_due" as const, graceUntil: "2026-11-08T00:00:00Z" }
    const html = renderStatic(h(CancelPlanDialog, { open: true, onClose: () => undefined, subscription: pastDue, audience: "student" }))
    expect(html).toContain("keeps working until " + formatBillingDate("2026-11-08T00:00:00Z"))
    expect(html).not.toContain(formatBillingDate(fx.activeSub.currentPeriodEnd as string))
    s.cancel = fakeMutation({ isSuccess: true, data: { ...wireSub, cancelAtPeriodEnd: true } })
    const done = renderStatic(h(CancelPlanDialog, { open: true, onClose: () => undefined, subscription: pastDue, audience: "student" }))
    expect(done).toContain("Cancelled. Your plan ends on " + formatBillingDate("2026-11-08T00:00:00Z"))
  })

  it("cannot be dismissed while the cancel is in flight", () => {
    const render = () =>
      renderStatic(h(CancelPlanDialog, { open: true, onClose: () => undefined, subscription: fx.activeSub, audience: "student" }))
    expect(render()).toContain('data-dismissible="true"')
    s.cancel = fakeMutation({ isPending: true })
    expect(render()).toContain('data-dismissible="false"')
  })

  it("keeps the result and failure live regions mounted", () => {
    const html = renderStatic(h(CancelPlanDialog, { open: true, onClose: () => undefined, subscription: fx.activeSub, audience: "student" }))
    expect(html).toContain('role="status"')
    expect(html).toContain('role="alert"')
  })
})

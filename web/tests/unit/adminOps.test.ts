import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  canReconcile,
  jobOutcomeText,
  jobRunsText,
  paymentTone,
  problemCount,
  PROBLEM_SECTIONS,
  reconcileNotice,
  sectionCount,
  webhookErrorText,
} from "@/lib/adminOpsModel"
import { ApiError } from "@/lib/api"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({ payments: null as unknown, problems: null as unknown, health: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useAdminPayments: () => s.payments,
  useProblemQueue: () => s.problems,
  useBillingHealth: () => s.health,
  useReconcilePayment: () => fakeMutation(),
  useRefundPayment: () => fakeMutation(),
  useVoidPayment: () => fakeMutation(),
}))

import { Health } from "@/portals/admin/screens/billing/Health"
import { Payments } from "@/portals/admin/screens/billing/Payments"

const infinite = (pages: unknown[]) => ({ ...okQuery({ pages, pageParams: [null] }), hasNextPage: false, isFetchingNextPage: false, fetchNextPage: vi.fn() })
const emptyQueue = { mismatches: [], stalePending: [], missingCallbacks: [], hmacFailures: [], hmacFailures24h: 0, refundsNeedingAttention: [] }
const CLEAR = "No payment problems right now."

beforeEach(() => {
  s.payments = infinite([{ items: [fx.adminPayment, { ...fx.adminPayment, id: "pay2", status: "pending", paidAt: null }], nextCursor: null }])
  s.problems = okQuery(fx.problems)
  s.health = okQuery(fx.health)
})

describe("ops model", () => {
  it("labels sections, counts problems and describes webhooks and jobs", () => {
    expect(PROBLEM_SECTIONS.map((x) => x.label)).toEqual([
      "Amount mismatches",
      "Pending over an hour",
      "Missing callbacks",
      "HMAC failures",
      "Refunds needing attention",
    ])
    expect(problemCount(fx.problems)).toBe(2)
    expect(problemCount(emptyQueue)).toBe(0)
    expect(webhookErrorText(fx.health)).toBe("1.5% failed (3 HMAC failures, 197 verified) in 24 hours")
    expect(webhookErrorText({ ...fx.health, webhookErrorRate: null })).toBe("No webhooks in 24 hours")
    expect(jobOutcomeText(fx.health.jobs[2])).toBe("Never run")
    expect(jobOutcomeText(fx.health.jobs[1])).toBe("Failed: drift on 2 grants (1 in a row)")
    expect(jobOutcomeText(fx.health.jobs[0])).toBe("OK")
    expect(canReconcile("pending")).toBe(true)
    expect(canReconcile("paid")).toBe(false)
  })

  it("reconciles only what Paymob can still change", () => {
    expect(["created", "pending", "failed"].every((x) => canReconcile(x as never))).toBe(true)
    expect(["paid", "failed_mismatch", "refunded", "partially_refunded", "voided"].some((x) => canReconcile(x as never))).toBe(false)
  })

  it("counts the 24-hour HMAC figure when the server listed fewer rows than it counted", () => {
    const capped = { ...emptyQueue, hmacFailures: [fx.problems.hmacFailures[0]], hmacFailures24h: 40 }
    expect(sectionCount(capped, "hmacFailures")).toBe(40)
    expect(problemCount({ ...emptyQueue, hmacFailures24h: 3 })).toBe(3)
  })

  it("keeps the failure colour for a payment that really failed", () => {
    expect(paymentTone("failed")).toBe("err")
    expect(paymentTone("failed_mismatch")).toBe("err")
    expect(["created", "pending", "paid", "refunded", "voided", "partially_refunded"].map((x) => paymentTone(x as never))).not.toContain("err")
  })

  it("words one HMAC failure and each job's totals", () => {
    expect(webhookErrorText({ ...fx.health, hmacFailures: 1 })).toContain("(1 HMAC failure,")
    expect(jobRunsText(fx.health.jobs[0])).toBe("40 runs")
    expect(jobRunsText(fx.health.jobs[1])).toBe("10 runs, 1 failed")
    expect(jobRunsText(fx.health.jobs[2])).toBe("No runs recorded")
  })

  it("says what Paymob reported without guessing what it said before", () => {
    expect(reconcileNotice({ id: "pay7", paymobOrderId: "PM-7", status: "pending" })).toBe("Checked with Paymob. Order PM-7 is pending.")
    expect(reconcileNotice({ id: "pay7", paymobOrderId: null, status: "failed_mismatch" })).toBe("Checked with Paymob. Order pay7 is failed mismatch.")
  })
})

describe("Payments", () => {
  it("shows the problem queue above the list with reconcile actions", () => {
    const html = renderStatic(h(Payments))
    expect(html.indexOf("Amount mismatches")).toBeLessThan(html.indexOf(">All payments<"))
    expect(html).toContain("PM-7")
    expect(html).toContain("bad hmac")
    expect(html).toContain("Reconcile")
    expect(html).toContain("Refund")
  })

  it("says the queue is clear only after a successful load", () => {
    s.problems = okQuery(emptyQueue)
    expect(renderStatic(h(Payments))).toContain(CLEAR)
  })

  it("never says the queue is clear while it is loading, failed or listing problems", () => {
    s.problems = pendingQuery()
    expect(renderStatic(h(Payments))).not.toContain(CLEAR)
    s.problems = errorQuery(new ApiError(500, "boom"))
    const failed = renderStatic(h(Payments))
    expect(failed).not.toContain(CLEAR)
    expect(failed).toContain("load the problem queue")
    s.problems = okQuery(fx.problems)
    expect(renderStatic(h(Payments))).not.toContain(CLEAR)
    // Only the 24-hour HMAC count is non-zero: still a problem.
    s.problems = okQuery({ ...emptyQueue, hmacFailures24h: 3 })
    const counted = renderStatic(h(Payments))
    expect(counted).not.toContain(CLEAR)
    expect(counted).toContain("HMAC failures")
  })

  it("offers Reconcile only on payments Paymob can still change, in the queue and the list", () => {
    s.problems = okQuery({ ...fx.problems, stalePending: [{ ...fx.adminPayment, id: "pay8", status: "pending", paymobOrderId: "PM-8", paidAt: null }] })
    const html = renderStatic(h(Payments))
    expect(html).toContain('aria-label="Reconcile pay2"')
    expect(html).toContain('aria-label="Reconcile pay8"')
    // paid (list) and failed_mismatch (queue) are settled.
    expect(html).not.toContain('aria-label="Reconcile pay1"')
    expect(html).not.toContain('aria-label="Reconcile pay7"')
  })

  it("shows a refund with no confirmed outcome as unknown, never failed or declined", () => {
    const refund = { id: "r1", kind: "refund" as const, status: "unknown" as const, amountMinor: 5000, reason: "duplicate charge", adminUserId: "a1", clawedBackUnits: 0, createdAt: "2026-11-05T06:00:00Z", updatedAt: "2026-11-05T06:30:00Z" }
    s.problems = okQuery({ ...emptyQueue, refundsNeedingAttention: [refund] })
    const html = renderStatic(h(Payments))
    const queue = html.slice(0, html.indexOf(">All payments<"))
    expect(queue).toContain("outcome unknown")
    expect(queue).toContain("duplicate charge")
    expect(queue).not.toMatch(/declined|failed/i)
  })

  it("shows a failed read of the list as an error, not as an empty list", () => {
    s.payments = { ...errorQuery(new ApiError(500, "boom")), hasNextPage: false, isFetchingNextPage: false, fetchNextPage: vi.fn() }
    const html = renderStatic(h(Payments))
    expect(html).toContain("load payments")
    expect(html).not.toContain("No payments")
  })

  it("lists payer and beneficiary ids, the purpose and the Paymob ids", () => {
    const html = renderStatic(h(Payments))
    expect(html).toContain("/platform/billing/customers/u1")
    expect(html).toContain("/platform/billing/customers/u2")
    expect(html).toContain("Subscription first")
    expect(html).toContain("TX-1")
  })

  it("offers Load more only while there is a next page", () => {
    expect(renderStatic(h(Payments))).not.toContain("Load more")
    s.payments = { ...(s.payments as object), hasNextPage: true }
    expect(renderStatic(h(Payments))).toContain("Load more")
  })

  it("tells an empty list apart from an empty filter result", () => {
    s.payments = infinite([{ items: [], nextCursor: null }])
    expect(renderStatic(h(Payments))).toContain("No payments yet.")
  })
})

describe("Health", () => {
  it("lists job outcomes and failure counts", () => {
    const html = renderStatic(h(Health))
    expect(html).toContain("billing.reconcile_pending")
    expect(html).toContain("Failed: drift on 2 grants")
    expect(html).toContain("Never run")
    expect(html).toContain("1.5% failed")
    expect(html).toContain("Renewal failures")
    expect(html).toContain("Past due now")
  })

  it("shows a failed read as an error with no figures", () => {
    s.health = errorQuery(new ApiError(500, "boom"))
    const html = renderStatic(h(Health))
    expect(html).toContain("load billing health")
    expect(html).not.toContain("Renewal failures")
  })

  it("says the last success of a failing job and the window the counts cover", () => {
    const html = renderStatic(h(Health))
    expect(html).toContain("last success 4 Nov 2026, 02:00 UTC")
    expect(html).toContain("last 24 hours")
  })
})

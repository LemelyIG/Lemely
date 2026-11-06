import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fx } from "./support/billingFixtures"
import { errorQuery, okQuery, pendingQuery, renderStatic } from "./support/billingRender"
import {
  actionLabel,
  jobChargeText,
  jobEstimateText,
  jobStatusText,
  purposeLabel,
  receiptStatusText,
} from "@/lib/usageHistoryModel"

const s = vi.hoisted(() => ({ history: null as unknown, receipts: null as unknown }))
vi.mock("@/lib/hooks/useUsageApi", () => ({ useUsageHistory: () => s.history }))
vi.mock("@/lib/hooks/useBillingApi", () => ({ useReceipts: () => s.receipts }))

import { ReceiptsView } from "@/portals/billing/Receipts"
import { UsageHistoryView } from "@/portals/billing/UsageHistory"

const infinite = (pages: unknown[], hasNextPage = false) => ({
  ...okQuery({ pages, pageParams: [null] }),
  hasNextPage,
  isFetchingNextPage: false,
  fetchNextPage: vi.fn(),
})

beforeEach(() => {
  s.history = infinite([fx.history])
  s.receipts = okQuery({ receipts: [fx.receipt] })
})

describe("usage history model", () => {
  it("labels actions and formats estimate and charge from the display values", () => {
    expect(actionLabel("mark_paper")).toBe("Paper marking")
    expect(actionLabel("study_plan")).toBe("Weekly study plan")
    expect(actionLabel("generate_flashcards")).toBe("Flashcard generation")
    expect(jobEstimateText(fx.job)).toBe("3–5 credits")
    expect(jobEstimateText({ ...fx.job, estimateCredits: [4, 4] })).toBe("4 credits")
    expect(jobChargeText(fx.job)).toBe("4 credits")
    const plan = { ...fx.job, paidBy: "allowance" as const, credits: null, percentOfPlan: 3, estimateCredits: null, estimatePercentOfPlan: [2, 4] as [number, number] }
    expect(jobEstimateText(plan)).toBe("2–4% of plan")
    expect(jobChargeText(plan)).toBe("3% of plan")
    const mixed = { ...plan, paidBy: "mixed" as const, percentOfPlan: 1, credits: 2, estimateCredits: [1, 3] as [number, number] }
    expect(jobEstimateText(mixed)).toBe("2–4% of plan + 1–3 credits")
    expect(jobChargeText(mixed)).toBe("1% of plan + 2 credits")
    expect(jobEstimateText({ ...fx.job, estimateCredits: null })).toBe("—")
  })

  it("says failed jobs cost nothing and shows debt", () => {
    expect(jobChargeText({ ...fx.job, status: "released", credits: null, paidBy: "none" })).toBe("No charge")
    expect(jobChargeText({ ...fx.job, status: "expired", credits: null, paidBy: "none" })).toBe("No charge")
    expect(jobStatusText({ ...fx.job, status: "open", credits: null })).toBe("Running")
    expect(jobChargeText({ ...fx.job, credits: 9, debtCredits: 4 })).toBe("9 credits (4 credits went below zero)")
  })

  it("labels payment purposes and refunds", () => {
    expect(purposeLabel("extra_seats")).toBe("Extra seats")
    expect(receiptStatusText(fx.receipt)).toBeNull()
    expect(receiptStatusText({ ...fx.receipt, status: "refunded" })).toBe("Refunded")
    expect(receiptStatusText({ ...fx.receipt, status: "partially_refunded" })).toBe("Partly refunded")
  })
})

describe("UsageHistoryView", () => {
  it("renders a table with estimate and actual columns", () => {
    const html = renderStatic(h(UsageHistoryView, { backHref: "/student/billing" }))
    expect(html).toContain("<table")
    expect(html).toContain("Estimate")
    expect(html).toContain("Charged")
    expect(html).toContain("Paper marking")
    expect(html).toContain("3–5 credits")
  })

  it("offers more pages while there is a cursor", () => {
    s.history = infinite([{ jobs: [fx.job], nextCursor: "n2" }], true)
    expect(renderStatic(h(UsageHistoryView, { backHref: "/teacher/billing" }))).toContain("Load more")
  })

  it("offers no more pages on the last one", () => {
    expect(renderStatic(h(UsageHistoryView, { backHref: "/teacher/billing" }))).not.toContain("Load more")
  })

  it("explains an empty history", () => {
    s.history = infinite([{ jobs: [], nextCursor: null }])
    expect(renderStatic(h(UsageHistoryView, { backHref: "/x" }))).toContain("No usage yet.")
  })

  it("says what a failed job and a debt row cost", () => {
    s.history = infinite([
      {
        jobs: [
          { ...fx.job, jobId: "j2", status: "released", credits: null, paidBy: "none" },
          { ...fx.job, jobId: "j3", credits: 9, debtCredits: 4 },
        ],
        nextCursor: null,
      },
    ])
    const html = renderStatic(h(UsageHistoryView, { backHref: "/x" }))
    expect(html).toContain("No charge")
    expect(html).toContain("Failed, not charged")
    expect(html).toContain("went below zero")
  })

  it("keeps the heading, with a loading and an error state under it", () => {
    s.history = pendingQuery()
    expect(renderStatic(h(UsageHistoryView, { backHref: "/x" }))).toContain("Usage history")
    s.history = errorQuery(new Error("boom"))
    const html = renderStatic(h(UsageHistoryView, { backHref: "/x" }))
    expect(html).toContain("load your usage history")
    expect(html).toContain("Try again")
  })
})

describe("ReceiptsView", () => {
  it("lists money receipts with description, purpose and amount", () => {
    const html = renderStatic(h(ReceiptsView, { backHref: "/student/billing" }))
    expect(html).toContain("500 credits")
    expect(html).toMatch(/EGP\s150\.00/)
    expect(html).toContain("Credit pack")
  })

  it("names a refunded payment without pricing the refund", () => {
    s.receipts = okQuery({ receipts: [{ ...fx.receipt, status: "partially_refunded" }] })
    expect(renderStatic(h(ReceiptsView, { backHref: "/x" }))).toContain("Partly refunded")
  })

  it("explains an empty list and links back from it", () => {
    s.receipts = okQuery({ receipts: [] })
    const html = renderStatic(h(ReceiptsView, { backHref: "/x" }))
    expect(html).toContain("No receipts yet.")
    expect(html).toContain('href="/x"')
  })

  it("keeps the heading, with a loading and an error state under it", () => {
    s.receipts = pendingQuery()
    expect(renderStatic(h(ReceiptsView, { backHref: "/x" }))).toContain("Receipts")
    s.receipts = errorQuery(new Error("boom"))
    expect(renderStatic(h(ReceiptsView, { backHref: "/x" }))).toContain("load your receipts")
  })
})

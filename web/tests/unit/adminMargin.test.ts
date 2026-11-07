import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { accuracyFlag, costByActionBars, defaultRange, formatShare, formatUsd, marginShare, rangeProblem, revenueBars } from "@/lib/marginModel"
import { fx } from "./support/billingFixtures"
import { errorQuery, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const noRate = { ...fx.margin, egpPerUsd: null, costMinor: null, marginMinor: null }

const s = vi.hoisted(() => ({ report: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({ useMarginReport: () => s.report }))
vi.mock("@/components/ui/lazy-chart", () => ({
  BarChart: (p: { ariaLabel: string }) => h("div", { "data-chart": "bar", "aria-label": p.ariaLabel }),
}))

import { Margin } from "@/portals/admin/screens/billing/Margin"

beforeEach(() => {
  s.report = okQuery(fx.margin)
})

describe("margin model", () => {
  it("computes the margin share against net revenue, or null without an EGP cost", () => {
    expect(marginShare(fx.margin)).toBeCloseTo(1179400 / 1400000)
    expect(marginShare({ ...fx.margin, marginMinor: null })).toBeNull()
  })

  it("has no margin share without positive net revenue, and keeps a loss negative", () => {
    expect(marginShare({ ...fx.margin, revenue: { ...fx.margin.revenue, netMinor: 0 } })).toBeNull()
    expect(marginShare({ ...fx.margin, marginMinor: -300000 })).toBeCloseTo(-300000 / 1400000)
    expect(formatShare(-0.214)).toBe("-21%")
    expect(formatShare(0.842)).toBe("84%")
  })

  it("builds revenue bars in EGP and cost-by-action bars in USD", () => {
    expect(revenueBars(fx.margin)).toEqual([
      { label: "Recurring", value: 11500 },
      { label: "Packs", value: 2700 },
      { label: "Refunded", value: 200 },
    ])
    expect(costByActionBars(fx.margin)).toEqual([
      { label: "mark_paper", value: 38.12 },
      { label: "Unattributed", value: 0.4 },
    ])
  })

  it("flags estimators that miss too often", () => {
    expect(accuracyFlag({ ...fx.margin.accuracy[0], shareOutside: 0.25 })).toBe("Retune")
    expect(accuracyFlag(fx.margin.accuracy[0])).toBeNull()
    expect(accuracyFlag({ ...fx.margin.accuracy[0], shareOutside: 0.2 })).toBeNull()
  })

  it("defaults to the last 90 days as whole UTC days", () => {
    expect(defaultRange(new Date("2026-11-05T12:00:00Z"))).toEqual({ from: "2026-08-07", to: "2026-11-05" })
    // 23:30 UTC is still the 5th; a local-time round would roll it to the 6th east of UTC.
    expect(defaultRange(new Date("2026-11-05T23:30:00Z"))).toEqual({ from: "2026-08-07", to: "2026-11-05" })
    expect(defaultRange(new Date("2026-11-06T00:30:00Z"))).toEqual({ from: "2026-08-08", to: "2026-11-06" })
  })

  it("names the field that makes a range unsendable", () => {
    expect(rangeProblem({ from: "2026-08-07", to: "2026-11-05" })).toBeNull()
    expect(rangeProblem({ from: "2026-11-05", to: "2026-11-05" })).toBeNull()
    expect(rangeProblem({ from: "", to: "2026-11-05" })?.field).toBe("from")
    expect(rangeProblem({ from: "2026-08-07", to: "" })?.field).toBe("to")
    expect(rangeProblem({ from: "2026-11-06", to: "2026-11-05" })?.field).toBe("to")
  })

  it("shows USD with cents and keeps sub-cent costs visible", () => {
    expect(formatUsd("44.120000")).toBe("USD 44.12")
    expect(formatUsd("0.400000")).toBe("USD 0.40")
    expect(formatUsd("0.000412")).toBe("USD 0.0004")
  })
})

describe("Margin", () => {
  it("renders the figures, both charts, the tables and exposure", () => {
    const html = renderStatic(h(Margin))
    expect(html).toContain("Outstanding debt")
    expect(html).toContain("340 credits")
    expect(html.match(/data-chart="bar"/g)?.length).toBe(2)
    expect(html).toContain("student_plus_m")
    expect(html).toContain("claude-haiku")
    expect(html).toContain("7%")
    expect(html).toContain("debtor@example.com")
    expect(html).toContain("USD 44.12")
    expect(html).toContain("1 USD = 50.00 EGP")
    expect(html).not.toContain("No USD to EGP rate set")
  })

  it("says when there is no USD to EGP rate, and shows no EGP cost or margin", () => {
    s.report = okQuery(noRate)
    const html = renderStatic(h(Margin))
    expect(html).toContain("No USD to EGP rate set")
    expect(html).toContain("USD 44.12")
    expect(html.match(/Not available/g)?.length).toBe(3)
    // A missing rate is never a zero cost, a zero margin or a percentage.
    expect(html).not.toContain("EGP 0.00")
    expect(html).not.toContain("1 USD =")
    expect(html).not.toMatch(/Margin share of net revenue<\/dt><dd[^>]*>\d/)
  })

  it("keeps a rate message for the rate, not for zero revenue", () => {
    s.report = okQuery({ ...fx.margin, revenue: { ...fx.margin.revenue, netMinor: 0, recurringMinor: 0, packsMinor: 0, refundedMinor: 0, byPlan: [] } })
    const html = renderStatic(h(Margin))
    expect(html).not.toContain("No USD to EGP rate set")
    expect(html).toContain("Margin share needs positive net revenue")
    expect(html).toContain("No payments were taken or refunded in this range.")
    expect(html).toContain("No plan revenue in this range.")
  })

  it("flags a retune row and states empty tables", () => {
    s.report = okQuery({
      ...fx.margin,
      accuracy: [{ ...fx.margin.accuracy[0], shareOutside: 0.31 }],
      cost: { ...fx.margin.cost, byAction: [], byPlan: [] },
      exposure: { ...fx.margin.exposure, topDebtors: [], debtors: 1 },
    })
    const html = renderStatic(h(Margin))
    expect(html).toContain("Retune")
    expect(html).toContain("No metered jobs settled in this range.")
    expect(html).toContain("No metered jobs in this range.")
    expect(html).toContain("Nobody owes credits.")
    expect(html).toContain("1 account<")
  })

  it("states an empty accuracy table", () => {
    s.report = okQuery({ ...fx.margin, accuracy: [] })
    expect(renderStatic(h(Margin))).toContain("nothing to score")
  })

  it("shows the loading skeleton and a readable failure", () => {
    s.report = pendingQuery()
    expect(renderStatic(h(Margin))).not.toContain("data-chart")
    s.report = errorQuery(new Error("boom"))
    const html = renderStatic(h(Margin))
    expect(html).toContain("Couldn&#x27;t load money and margin")
    expect(html).not.toContain("data-chart")
  })

  it("says plainly when the admin may not read the report", () => {
    s.report = errorQuery(new ApiError(403, "Forbidden"))
    const html = renderStatic(h(Margin))
    expect(html).toContain("You can&#x27;t see money and margin")
    expect(html).not.toContain("data-chart")
  })

  it("uses neither the error nor the gold role (debt and cost are not errors)", async () => {
    const { readFileSync } = await import("node:fs")
    const src = readFileSync("src/portals/admin/screens/billing/Margin.tsx", "utf8")
    expect(src).not.toMatch(/text-error|bg-error|tertiary/)
  })
})

import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import {
  MAX_RANGE_DAYS,
  accuracyFlag,
  costByActionBars,
  defaultRange,
  formatShare,
  formatUsd,
  marginShare,
  rangeProblem,
  rateParam,
  rateProblem,
  revenueBars,
  windowOf,
} from "@/lib/marginModel"
import { fx } from "./support/billingFixtures"
import { errorQuery, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const noRate = { ...fx.margin, egpPerUsd: null, egpPerUsdSource: null, costMinor: null, marginMinor: null }

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

  it("defaults to exactly 90 inclusive UTC days", () => {
    expect(defaultRange(new Date("2026-11-05T12:00:00Z"))).toEqual({ from: "2026-08-08", to: "2026-11-05" })
    // 23:30 UTC is still the 5th; a local-time round would roll it to the 6th east of UTC.
    expect(defaultRange(new Date("2026-11-05T23:30:00Z"))).toEqual({ from: "2026-08-08", to: "2026-11-05" })
    expect(defaultRange(new Date("2026-11-06T00:30:00Z"))).toEqual({ from: "2026-08-09", to: "2026-11-06" })
    const r = defaultRange(new Date("2026-11-05T12:00:00Z"))
    const w = windowOf(r)
    expect((Date.parse(w.end) - Date.parse(w.start)) / 86_400_000).toBe(90)
  })

  it("names the field that makes a range unsendable", () => {
    expect(rangeProblem({ from: "2026-08-07", to: "2026-11-05" })).toBeNull()
    expect(rangeProblem({ from: "2026-11-05", to: "2026-11-05" })).toBeNull()
    expect(rangeProblem({ from: "", to: "2026-11-05" })?.field).toBe("from")
    expect(rangeProblem({ from: "2026-08-07", to: "" })?.field).toBe("to")
    expect(rangeProblem({ from: "2026-11-06", to: "2026-11-05" })?.field).toBe("to")
  })

  it("rejects what the server refuses: more than 400 days, and a date that is not a full real day", () => {
    // 400 inclusive days is the longest window the server takes; 401 is a 422.
    expect(rangeProblem({ from: "2025-10-02", to: "2026-11-05" })).toBeNull()
    expect(rangeProblem({ from: "2025-10-01", to: "2026-11-05" })).toEqual({ field: "to", message: `A range can cover at most ${MAX_RANGE_DAYS} days.` })
    // A date input accepts a five-digit year; as text it sorts after 2026 and would pass an order check.
    expect(rangeProblem({ from: "2026-01-01", to: "12345-01-01" })?.field).toBe("to")
    expect(rangeProblem({ from: "12345-01-01", to: "2026-01-01" })?.field).toBe("from")
    expect(rangeProblem({ from: "2026-02-30", to: "2026-03-05" })?.field).toBe("from")
    expect(rangeProblem({ from: "9999-12-30", to: "9999-12-31" })?.field).toBe("from")
    expect(rangeProblem({ from: "1969-12-31", to: "1970-01-02" })?.field).toBe("from")
    expect(rangeProblem({ from: "9998-12-30", to: "9998-12-31" })).toBeNull()
    expect(rangeProblem({ from: "2026-2-3", to: "2026-03-05" })?.field).toBe("from")
  })

  it("sends a half-open window that ends at the start of the day after `to`", () => {
    expect(windowOf({ from: "2026-10-01", to: "2026-11-05" })).toEqual({ start: "2026-10-01T00:00:00Z", end: "2026-11-06T00:00:00Z" })
    expect(windowOf({ from: "2026-12-31", to: "2026-12-31" })).toEqual({ start: "2026-12-31T00:00:00Z", end: "2027-01-01T00:00:00Z" })
    expect(windowOf({ from: "2028-02-28", to: "2028-02-28" }).end).toBe("2028-02-29T00:00:00Z")
    expect(windowOf({ from: "2028-02-29", to: "2028-02-29" }).end).toBe("2028-03-01T00:00:00Z")
    expect(() => windowOf({ from: "2026-02-30", to: "2026-03-05" })).toThrow(RangeError)
    // The day after the last allowed year is still four digits; 9999-12-31 would roll into a five-digit year.
    expect(windowOf({ from: "9998-12-31", to: "9998-12-31" }).end).toBe("9999-01-01T00:00:00Z")
    expect(() => windowOf({ from: "9999-12-31", to: "9999-12-31" })).toThrow(RangeError)
  })

  it("accepts a USD to EGP rate above 0 and up to 10,000, and says why otherwise", () => {
    expect(rateProblem("")).toBeNull()
    expect(rateProblem("50")).toBeNull()
    expect(rateProblem(" 48.5 ")).toBeNull()
    expect(rateProblem("10000")).toBeNull()
    expect(rateProblem("10000.01")).toMatch(/at most 10,000/)
    expect(rateProblem("0")).toMatch(/more than 0/)
    expect(rateProblem("-5")).toMatch(/number/)
    expect(rateProblem("1e3")).toMatch(/number/)
    expect(rateProblem("fifty")).toMatch(/number/)
    expect(rateProblem("48.1234")).toBeNull()
    expect(rateProblem("48.12345")).toMatch(/4 decimal/)
    expect(rateParam("  ")).toBeNull()
    expect(rateParam(" 48.5 ")).toBe("48.5")
  })

  it("shows USD with cents, keeps sub-cent costs visible and never shows a real cost as zero", () => {
    expect(formatUsd("44.120000")).toBe("USD 44.12")
    expect(formatUsd("0.400000")).toBe("USD 0.40")
    expect(formatUsd("0.000412")).toBe("USD 0.0004")
    expect(formatUsd("0.000049")).toBe("under USD 0.0001")
    expect(formatUsd("0.000050")).toBe("USD 0.0001")
    expect(formatUsd("0.000000")).toBe("USD 0.00")
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
    expect(html).toContain("1 USD = 50 EGP (default)")
    expect(html).toContain("Metered settled cost")
    expect(html).not.toContain("LLM cost")
    expect(html).not.toContain("No USD to EGP rate set")
  })

  it("says when there is no USD to EGP rate, and shows no EGP cost or margin", () => {
    s.report = okQuery(noRate)
    const html = renderStatic(h(Margin))
    expect(html).toContain("No USD to EGP rate set")
    expect(html).toContain("Set a default in billing rules, or enter an EGP per USD rate above, to work out cost in EGP and margin.")
    expect(html).not.toContain("/platform/billing/catalogue")
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

  it("marks stale figures as updating while a new range loads", () => {
    s.report = { ...okQuery(fx.margin), isPlaceholderData: true }
    const html = renderStatic(h(Margin))
    expect(html).toContain("Updating for the new range or rate.")
    expect(html).toContain('aria-busy="true"')
    s.report = okQuery(fx.margin)
    expect(renderStatic(h(Margin))).not.toContain("Updating for")
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

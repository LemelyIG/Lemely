import { createElement as h } from "react"
import { describe, expect, it } from "vitest"
import { CreditBalanceCard } from "@/components/billing/credit-balance"
import { DebtNotice } from "@/components/billing/debt-notice"
import { UsageMeterCard } from "@/components/billing/usage-meter"
import { fx } from "./support/billingFixtures"
import { renderStatic } from "./support/billingRender"

const now = new Date("2026-11-05T00:00:00Z")

describe("UsageMeterCard", () => {
  it("renders the allowance bar with an accessible name and no note under 80%", () => {
    const html = renderStatic(h(UsageMeterCard, { meter: fx.meter }))
    expect(html).toContain('role="progressbar"')
    expect(html).toMatch(/Usage 63%, resets/)
    expect(html).not.toContain("Most of this month")
  })

  it("says credits pay once the plan is used up, without an error fill", () => {
    const html = renderStatic(
      h(UsageMeterCard, { meter: { ...fx.meter, allowance: { fraction: 1, resetsAt: "2026-12-01T00:00:00Z" } } }),
    )
    expect(html).toContain("Credits pay from here.")
    expect(html).not.toContain("bg-error")
  })

  it("lists seat meters and explains a credits-only account", () => {
    const seats = renderStatic(
      h(UsageMeterCard, {
        meter: {
          ...fx.meter,
          allowance: null,
          seats: [
            { teacherMemberId: "m1", teacherUserId: "u9", fraction: 0.4, resetsAt: "2026-12-01T00:00:00Z" },
          ],
        },
      }),
    )
    expect(seats).toContain("Seat from your teacher: 40% used")
    const none = renderStatic(h(UsageMeterCard, { meter: { ...fx.meter, allowance: null, seats: [] } }))
    expect(none).toContain("No plan allowance. Usage comes from your credits.")
  })
})

describe("CreditBalanceCard", () => {
  it("shows the total and the expiry breakdown, soonest first", () => {
    const html = renderStatic(h(CreditBalanceCard, { credits: fx.meter.credits, now, buyHref: "/student/billing/plans#packs" }))
    expect(html).toContain("700")
    expect(html.indexOf("200 credits expire")).toBeLessThan(html.indexOf("500 credits expire"))
    expect(html).toContain("Expires soon")
  })

  it("offers a way to buy when there are no credits, and none when buying is someone else's job", () => {
    const empty = { total: 0, buckets: [] }
    expect(renderStatic(h(CreditBalanceCard, { credits: empty, now, buyHref: "/x#packs" }))).toContain("Buy credits")
    expect(renderStatic(h(CreditBalanceCard, { credits: empty, now, buyHref: null }))).not.toContain("Buy credits")
  })
})

describe("DebtNotice", () => {
  it("renders nothing without debt and a status panel with it", () => {
    expect(renderStatic(h(DebtNotice, { debtUnits: 0, audience: "student", buyHref: null }))).toBe("")
    const html = renderStatic(h(DebtNotice, { debtUnits: 12, audience: "student", buyHref: "/x#packs" }))
    expect(html).toContain('role="status"')
    expect(html).toContain("12 credits more than your balance")
    expect(html).toContain("Buy credits")
    expect(html).not.toMatch(/bg-error|text-error|tertiary/)
  })
})

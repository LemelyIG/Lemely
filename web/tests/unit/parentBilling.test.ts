import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { renderAt, renderStatic, okQuery, pendingQuery } from "./support/billingRender"

const s = vi.hoisted(() => ({ children: null as unknown, overviewProps: [] as Array<Record<string, unknown>> }))
vi.mock("@/lib/hooks/useParentApi", () => ({ useChildren: () => s.children }))
vi.mock("@/portals/billing/BillingOverview", () => ({
  BillingOverview: (p: Record<string, unknown>) => {
    s.overviewProps.push(p)
    return h("h1", null, p.heading as string)
  },
}))

import { ChildBillingLink, ParentChildBilling } from "@/portals/billing/ParentBilling"

beforeEach(() => {
  s.overviewProps = []
  s.children = okQuery({ children: [{ childId: "c1", displayName: "Omar", classes: [] }] })
})

describe("ParentChildBilling", () => {
  it("scopes the overview to the child and names them", () => {
    const html = renderAt(h(ParentChildBilling), "/parent/children/:childId/billing", "/parent/children/c1/billing")
    expect(html).toContain("Plan and billing for Omar")
    expect(s.overviewProps[0]).toMatchObject({
      scope: { role: "parent", childId: "c1" },
      audience: "student",
      beneficiaryId: "c1",
    })
    expect(typeof s.overviewProps[0].extra).toBe("object")
  })

  it("falls back to a generic heading before the child list loads", () => {
    s.children = pendingQuery()
    const html = renderAt(h(ParentChildBilling), "/parent/children/:childId/billing", "/parent/children/c1/billing")
    expect(html).toContain(">Plan and billing<")
  })
})

describe("ChildBillingLink", () => {
  it("links to the child's billing page", () => {
    expect(renderStatic(h(ChildBillingLink, { childId: "c1" }))).toContain('href="/parent/children/c1/billing"')
  })
})

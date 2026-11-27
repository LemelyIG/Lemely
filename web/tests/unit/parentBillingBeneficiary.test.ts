import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { okQuery, pendingQuery, renderAt } from "./support/billingRender"

const s = vi.hoisted(() => ({ children: null as unknown, overviewProps: [] as Array<Record<string, unknown>> }))
vi.mock("@/lib/hooks/useParentApi", () => ({ useChildren: () => s.children }))
vi.mock("@/portals/billing/BillingOverview", () => ({
  BillingOverview: (p: Record<string, unknown>) => {
    s.overviewProps.push(p)
    return h("h1", null, p.heading as string)
  },
}))

import { ParentChildBilling } from "@/portals/billing/ParentBilling"

const visit = () => renderAt(h(ParentChildBilling), "/parent/children/:childId/billing", "/parent/children/c1/billing")

beforeEach(() => {
  s.overviewProps = []
})

describe("ParentChildBilling beneficiary name", () => {
  it("hands the child's display name to the overview so its error heading can name them", () => {
    s.children = okQuery({ children: [{ childId: "c1", displayName: "Omar", classes: [] }] })
    visit()
    expect(s.overviewProps[0]).toMatchObject({ beneficiaryName: "Omar" })
  })

  it("passes no name before the child list loads", () => {
    s.children = pendingQuery()
    visit()
    expect(s.overviewProps[0]?.beneficiaryName).toBeUndefined()
  })
})

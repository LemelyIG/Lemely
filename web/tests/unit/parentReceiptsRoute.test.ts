import { matchRoutes } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { parentRoute } from "@/portals/parent"
import { receiptsTrail } from "@/portals/parent/trail"

const one = [{ childId: "c1" }]
const two = [{ childId: "c1" }, { childId: "c2" }]

describe("parent receipts trail", () => {
  it("leads back to the list when there are several children", () => {
    expect(receiptsTrail("/parent/billing/receipts", two)).toEqual([
      { label: "Your children", to: "/parent" },
      { label: "Receipts" },
    ])
  })

  it("leads back to the child's overview when there is one child", () => {
    expect(receiptsTrail("/parent/billing/receipts", one)).toEqual([
      { label: "Overview", to: "/parent/children/c1" },
      { label: "Receipts" },
    ])
  })

  it("shows nothing while the child list is pending or empty", () => {
    expect(receiptsTrail("/parent/billing/receipts", undefined)).toBeNull()
    expect(receiptsTrail("/parent/billing/receipts", [])).toBeNull()
  })

  it("ignores a trailing slash and every other path", () => {
    expect(receiptsTrail("/parent/billing/receipts/", one)).not.toBeNull()
    expect(receiptsTrail("/parent/children/c1/billing", one)).toBeNull()
    expect(receiptsTrail("/parent", two)).toBeNull()
  })
})

describe("parent receipts route", () => {
  const lastRoute = (path: string) => matchRoutes([parentRoute], path)?.at(-1)?.route

  it("mounts /parent/billing/receipts as its own screen", () => {
    const route = lastRoute("/parent/billing/receipts")
    expect(route?.path).toBe("billing/receipts")
    expect((route?.handle as { title?: string } | undefined)?.title).toBe("Receipts")
  })

  it("has no child usage-history route (M6)", () => {
    expect(lastRoute("/parent/children/c1/billing/history")?.path).not.toBe("billing/history")
    expect(lastRoute("/parent/children/c1/billing/history")?.path).not.toMatch(/history/)
  })
})

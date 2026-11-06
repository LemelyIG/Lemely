import { describe, expect, it } from "vitest"
import { requestKeyOf, resolveBlock } from "@/lib/meteredGate"
import { fx } from "./support/billingFixtures"

const req = { action: "regrade" as const, paperId: "p1" }

describe("resolveBlock", () => {
  it("is null when the estimate allows the job and nothing was caught", () => {
    expect(resolveBlock(fx.estimate, null, requestKeyOf(req))).toBeNull()
    expect(resolveBlock(undefined, null, null)).toBeNull()
  })

  it("blocks from the estimate's reason", () => {
    expect(resolveBlock({ ...fx.estimate, blockedReason: "insufficient_credits" }, null, requestKeyOf(req))).toEqual({
      reason: "insufficient_credits",
      estimate: null,
    })
  })

  it("prefers a 402 caught for the same request, and drops it once the request changes", () => {
    const caught = { key: requestKeyOf(req), block: { reason: "outstanding_debt" as const, estimate: [3, 5] as [number, number] } }
    expect(resolveBlock(fx.estimate, caught, requestKeyOf(req))?.reason).toBe("outstanding_debt")
    const changed = requestKeyOf({ ...req, paperId: "p2" })
    expect(resolveBlock(fx.estimate, caught, changed)).toBeNull()
  })

  it("keys requests by value", () => {
    expect(requestKeyOf(req)).toBe(requestKeyOf({ ...req }))
    expect(requestKeyOf(null)).toBeNull()
  })
})

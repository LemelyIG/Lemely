import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { blockSourceOf, captureBlock, reconcileCaught, requestKeyOf, resolveBlock } from "@/lib/meteredGate"
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

const body = { error: "usage_blocked", reason: "insufficient_credits", estimate: [3, 5] }
const err402 = () => new ApiError(402, "402", undefined, undefined, body)

describe("captureBlock", () => {
  it("captures a 402 usage block against its request key", () => {
    expect(captureBlock(err402(), "k")).toEqual({ key: "k", block: { reason: "insufficient_credits", estimate: [3, 5] } })
  })

  it("ignores other errors and a missing request key", () => {
    expect(captureBlock(new ApiError(500, "x"), "k")).toBeNull()
    expect(captureBlock(new Error("x"), "k")).toBeNull()
    expect(captureBlock(err402(), null)).toBeNull()
  })
})

describe("reconcileCaught", () => {
  const caught = captureBlock(err402(), "A")

  it("keeps a block for its own key and drops it for another", () => {
    expect(reconcileCaught(caught, "A")).toBe(caught)
    expect(reconcileCaught(caught, "B")).toBeNull()
  })

  it("does not resurrect on A, B, A once the state follows the reconciled value", () => {
    let state = caught
    for (const key of ["B", "A"]) state = reconcileCaught(state, key)
    expect(state).toBeNull()
  })

  it("clear is the null state", () => {
    expect(reconcileCaught(null, "A")).toBeNull()
  })
})

describe("resolveBlock from a failed estimate", () => {
  it("maps a 402 on the estimate request itself", () => {
    expect(resolveBlock(undefined, null, "k", err402())?.reason).toBe("insufficient_credits")
    expect(resolveBlock(undefined, null, "k", new ApiError(500, "x"))).toBeNull()
  })
})

describe("blockSourceOf", () => {
  it("separates a start-action 402 from an estimate-driven block", () => {
    const caught = captureBlock(err402(), "k")
    const block = resolveBlock(fx.estimate, caught, "k")
    expect(blockSourceOf(block, caught, "k")).toBe("start")
    const fromEstimate = resolveBlock({ ...fx.estimate, blockedReason: "no_active_plan" }, null, "k")
    expect(blockSourceOf(fromEstimate, null, "k")).toBe("estimate")
    expect(blockSourceOf(null, null, "k")).toBeNull()
  })
})

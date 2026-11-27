import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { USAGE_BLOCK_REASONS } from "@/lib/billingTypes"
import { parseUsageBlock, usageBlockCopy } from "@/lib/usageBlock"

const body = { error: "usage_blocked", reason: "insufficient_credits", estimate: [3, 5] }

describe("parseUsageBlock", () => {
  it("reads the flat 402 body Phase 04's handler sends", () => {
    const err = new ApiError(402, "402 Payment Required", undefined, undefined, body)
    expect(parseUsageBlock(err)).toEqual({ reason: "insufficient_credits", estimate: [3, 5] })
  })

  it("also reads a 402 body nested in FastAPI's detail", () => {
    const err = new ApiError(402, "402", body, undefined, { detail: body })
    expect(parseUsageBlock(err)).toEqual({ reason: "insufficient_credits", estimate: [3, 5] })
  })

  it("keeps the reason when the estimate is missing or malformed", () => {
    const err = new ApiError(402, "402", undefined, undefined, { ...body, estimate: ["a"] })
    expect(parseUsageBlock(err)).toEqual({ reason: "insufficient_credits", estimate: null })
  })

  it("ignores other statuses, unknown reasons and non-ApiErrors", () => {
    expect(parseUsageBlock(new ApiError(403, "403", undefined, undefined, body))).toBeNull()
    expect(
      parseUsageBlock(new ApiError(402, "402", undefined, undefined, { ...body, reason: "nope" })),
    ).toBeNull()
    expect(parseUsageBlock(new Error("x"))).toBeNull()
    expect(parseUsageBlock(new ApiError(402, "402"))).toBeNull()
  })
})

describe("usageBlockCopy", () => {
  it("has a title, body and next step for every reason and audience", () => {
    for (const reason of USAGE_BLOCK_REASONS) {
      for (const audience of ["student", "teacher"] as const) {
        const copy = usageBlockCopy(reason, audience)
        expect(copy.title.length).toBeGreaterThan(0)
        expect(copy.body.length).toBeGreaterThan(0)
        expect(["buy_credits", "see_plans", "ask_teacher"]).toContain(copy.next)
        expect(copy.title + copy.body).not.toMatch(/[!—]/)
      }
    }
  })

  it("sends a student outside their seat's scope to buy credits, not to a plan page", () => {
    expect(usageBlockCopy("out_of_seat_scope", "student").next).toBe("buy_credits")
    expect(usageBlockCopy("no_active_plan", "student").next).toBe("see_plans")
  })
})

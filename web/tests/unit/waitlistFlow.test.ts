import { describe, expect, it } from "vitest"
import { WaitlistError } from "@/lib/waitlist-api"
import { EXPIRED_COPY, classifyStep2Failure, continueStep1, decideContinue, withRetry } from "@/portals/marketing/waitlist/flow"

describe("waitlist two-step flow decisions", () => {
  it("first Continue calls the server", () => {
    expect(decideContinue("")).toBe("call-server")
  })

  it("Back then Continue with a held token goes straight to step 2, with no second server call", () => {
    // Step 1 succeeded and returned a token; the visitor pressed Back from step 2.
    const token = "one-time-token"
    expect(decideContinue(token)).toBe("go-step-2")
    // Calling the server again would answer already_listed and drop the visitor out of step 2.
  })

  it("a 400 on step 2 is terminal (expired or used token), not a restart", () => {
    expect(classifyStep2Failure(new WaitlistError(400))).toBe("expired")
    expect(EXPIRED_COPY).toBe("Your email is saved. The details link expired, so we'll ask for the rest later.")
    expect(EXPIRED_COPY.toLowerCase()).not.toContain("start again")
  })

  it("other failures stay retryable", () => {
    expect(classifyStep2Failure(new WaitlistError(429))).toBe("rate")
    expect(classifyStep2Failure(new WaitlistError(0))).toBe("network")
    expect(classifyStep2Failure(new WaitlistError(500))).toBe("failed")
    expect(classifyStep2Failure(new Error("x"))).toBe("failed")
  })
})

describe("step 1 Continue, Back, Continue (the component drives this function)", () => {
  it("calls join exactly once and goes to step 2 both times", async () => {
    let calls = 0
    const join = async () => {
      calls++
      return { status: "created" as const, token: "one-time-token" }
    }
    const first = await continueStep1("", join)
    expect(first).toEqual({ kind: "joined", result: { status: "created", token: "one-time-token" } })
    // Step 2, then Back: the panel still holds the token. Continue again.
    const second = await continueStep1("one-time-token", join)
    expect(second).toEqual({ kind: "step-2", token: "one-time-token" })
    expect(calls).toBe(1)
  })

  it("reports a stop when validation or the challenge blocked the call", async () => {
    expect(await continueStep1("", async () => null)).toEqual({ kind: "stopped" })
  })
})

describe("withRetry", () => {
  it("retries a failing load, then gives up with the last error", async () => {
    let n = 0
    await expect(withRetry(async () => { n++; throw new Error("x") }, [0, 0])).rejects.toThrow("x")
    expect(n).toBe(3)
  })
  it("returns the first success", async () => {
    let n = 0
    expect(await withRetry(async () => { if (++n < 2) throw new Error("x"); return "ok" }, [0, 0])).toBe("ok")
  })
})

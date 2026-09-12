import { describe, expect, it, vi } from "vitest"
import {
  withRetry,
  gotoWithRetry,
  // @ts-expect-error — plain .mjs gate script, no type declarations by design.
} from "../../scripts/nav_retry.mjs"

/*
 * Packet A8 (`emp-env-navigation-flakiness`) — `scripts/nav_retry.mjs`'s
 * shared retry primitive, used by `scripts/audit.mjs`'s page navigations
 * and Lighthouse passes.
 */

describe("withRetry", () => {
  it("returns the result on the first successful attempt, no retry", async () => {
    const fn = vi.fn().mockResolvedValue("ok")
    const result = await withRetry(fn)
    expect(result).toBe("ok")
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it("retries after a failure and returns the eventual success", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("transient"))
      .mockResolvedValueOnce("ok")
    const result = await withRetry(fn, { attempts: 3 })
    expect(result).toBe("ok")
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it("throws the last error after exhausting every attempt", async () => {
    const fn = vi.fn().mockRejectedValue(new Error("still failing"))
    await expect(withRetry(fn, { attempts: 3 })).rejects.toThrow("still failing")
    expect(fn).toHaveBeenCalledTimes(3)
  })

  it("never calls fn more than attempts times", async () => {
    const fn = vi.fn().mockRejectedValue(new Error("nope"))
    await expect(withRetry(fn, { attempts: 2 })).rejects.toThrow()
    expect(fn).toHaveBeenCalledTimes(2)
  })
})

describe("gotoWithRetry", () => {
  it("calls page.goto with the given url and options", async () => {
    const page = { goto: vi.fn().mockResolvedValue(undefined) }
    await gotoWithRetry(page, "https://example.com/x", { waitUntil: "networkidle0" })
    expect(page.goto).toHaveBeenCalledWith("https://example.com/x", { waitUntil: "networkidle0" })
  })

  it("retries page.goto on failure up to the given attempts", async () => {
    const page = {
      goto: vi
        .fn()
        .mockRejectedValueOnce(new Error("net::ERR_CONNECTION_REFUSED"))
        .mockResolvedValueOnce(undefined),
    }
    await gotoWithRetry(page, "https://example.com/x", {}, 3)
    expect(page.goto).toHaveBeenCalledTimes(2)
  })
})

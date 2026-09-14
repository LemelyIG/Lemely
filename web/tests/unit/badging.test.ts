import { describe, expect, it, vi } from "vitest"
import { setAppBadge } from "@/lib/badging"

/*
 * Task 7 (B5a) · the Badging API wrapper `BadgeSync` and `sw.ts` both call.
 *
 * The Badging API is Chromium/Edge-only, so every call is defensive: an
 * injected `navigator`-like object stands in for the real one, matching
 * `haptic`'s and `useWakeLock`'s "every failure is a nicety" shape.
 */

describe("setAppBadge", () => {
  it("calls setAppBadge with a positive count", async () => {
    const setAppBadgeFn = vi.fn().mockResolvedValue(undefined)
    const clearAppBadgeFn = vi.fn().mockResolvedValue(undefined)
    const outcome = await setAppBadge(3, {
      setAppBadge: setAppBadgeFn,
      clearAppBadge: clearAppBadgeFn,
    })
    expect(setAppBadgeFn).toHaveBeenCalledWith(3)
    expect(clearAppBadgeFn).not.toHaveBeenCalled()
    expect(outcome).toBe(true)
  })

  it("clears the badge for a zero count", async () => {
    const setAppBadgeFn = vi.fn().mockResolvedValue(undefined)
    const clearAppBadgeFn = vi.fn().mockResolvedValue(undefined)
    const outcome = await setAppBadge(0, {
      setAppBadge: setAppBadgeFn,
      clearAppBadge: clearAppBadgeFn,
    })
    expect(clearAppBadgeFn).toHaveBeenCalledWith()
    expect(setAppBadgeFn).not.toHaveBeenCalled()
    expect(outcome).toBe(true)
  })

  it("returns false when the API is unsupported", async () => {
    expect(await setAppBadge(3, {})).toBe(false)
  })
})

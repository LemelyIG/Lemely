import { describe, expect, it, vi } from "vitest"
import { haptic } from "@/lib/haptics"

/*
 * Task 7 (B5a) · the Vibration API wrapper.
 *
 * `navigator.vibrate` is unsupported on iOS Safari and any desktop browser,
 * so every call here is a nicety, never a requirement — `haptic` reports
 * whether it actually fired (`false` when the API is absent) rather than
 * throwing, and takes an injected `navigator`-like object so this file is
 * testable under vitest's jsdom-less `environment: "node"`.
 */

describe("haptic", () => {
  it("returns false when vibrate is absent", () => {
    expect(haptic("tap", {})).toBe(false)
  })

  it("calls vibrate with the tap pattern", () => {
    const vibrate = vi.fn(() => true)
    haptic("tap", { vibrate })
    expect(vibrate).toHaveBeenCalledWith(10)
  })

  it("calls vibrate with the success pattern", () => {
    const vibrate = vi.fn(() => true)
    haptic("success", { vibrate })
    expect(vibrate).toHaveBeenCalledWith([10, 30, 10])
  })

  it("calls vibrate with the warning pattern", () => {
    const vibrate = vi.fn(() => true)
    haptic("warning", { vibrate })
    expect(vibrate).toHaveBeenCalledWith([30, 20, 30])
  })

  it("returns vibrate's own result", () => {
    const vibrate = vi.fn(() => false)
    expect(haptic("tap", { vibrate })).toBe(false)
  })
})

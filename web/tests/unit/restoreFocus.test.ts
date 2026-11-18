import { describe, expect, it } from "vitest"
import { focusReturnTarget } from "@/lib/restoreFocus"

const el = (isConnected = true, attrs: Record<string, string> = {}) => ({
  isConnected,
  getAttribute: (n: string) => attrs[n] ?? null,
})

describe("focusReturnTarget", () => {
  it("returns a connected opener", () => {
    const b = el()
    expect(focusReturnTarget(b, "c1")).toBe(b)
  })
  it("returns null for no opener, body or a detached opener", () => {
    expect(focusReturnTarget(null)).toBeNull()
    const body = el()
    expect(focusReturnTarget(body, "c1", body)).toBeNull()
    expect(focusReturnTarget(el(false))).toBeNull()
  })
  it("leaves a Radix Trigger to the Radix default", () => {
    expect(focusReturnTarget(el(true, { "aria-controls": "c1" }), "c1")).toBeNull()
    expect(focusReturnTarget(el(true, { "aria-controls": "other" }), "c1")).not.toBeNull()
  })
})

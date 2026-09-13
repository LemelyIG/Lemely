import { describe, expect, it } from "vitest"
import { overlayPhase, type OverlayState } from "@/lib/overlayPhase"

const STATES: OverlayState[] = ["closed", "open", "closing"]

describe("overlayPhase", () => {
  describe("open — always wins outright, including mid-exit", () => {
    it.each(STATES)("from %s, reducedMotion=false", (state) => {
      expect(overlayPhase(state, "open", false)).toBe("open")
    })
    it.each(STATES)("from %s, reducedMotion=true", (state) => {
      expect(overlayPhase(state, "open", true)).toBe("open")
    })
  })

  describe("close", () => {
    it("from open, reducedMotion=false, starts the exit", () => {
      expect(overlayPhase("open", "close", false)).toBe("closing")
    })

    it("from open, reducedMotion=true, skips straight to closed — nothing to animate", () => {
      expect(overlayPhase("open", "close", true)).toBe("closed")
    })

    it("from closed is a no-op", () => {
      expect(overlayPhase("closed", "close", false)).toBe("closed")
      expect(overlayPhase("closed", "close", true)).toBe("closed")
    })
  })

  describe("animationend", () => {
    it("from closing, finishes the exit", () => {
      expect(overlayPhase("closing", "animationend", false)).toBe("closed")
      expect(overlayPhase("closing", "animationend", true)).toBe("closed")
    })

    it("from open or closed, a stray event changes nothing", () => {
      expect(overlayPhase("open", "animationend", false)).toBe("open")
      expect(overlayPhase("closed", "animationend", false)).toBe("closed")
    })
  })

  it("a full open -> close -> animationend cycle", () => {
    let state: OverlayState = "closed"
    state = overlayPhase(state, "open", false)
    expect(state).toBe("open")
    state = overlayPhase(state, "close", false)
    expect(state).toBe("closing")
    state = overlayPhase(state, "animationend", false)
    expect(state).toBe("closed")
  })
})

import { describe, expect, it } from "vitest"
import { computeFit, fitStyle } from "../../src/portals/teacher/screens/review/useFillViewport"

describe("computeFit", () => {
  it("desktop with no bar reclaims the main padding", () => {
    expect(computeFit({ top: 96, parentPad: 24, barH: 0, keepPadding: false })).toEqual({ top: 96, clearance: 0, pad: 24 })
  })
  it("tablet with a visible tab bar clears the bar, not the padding", () => {
    expect(computeFit({ top: 96, parentPad: 24, barH: 63, keepPadding: false })).toEqual({ top: 96, clearance: 63, pad: 24 })
  })
  it("phone keeps whichever of padding and bar is taller", () => {
    expect(computeFit({ top: 96, parentPad: 88, barH: 63, keepPadding: true }).clearance).toBe(88)
    expect(computeFit({ top: 96, parentPad: 24, barH: 63, keepPadding: true }).clearance).toBe(63)
  })
  it("rounds and ignores negative or NaN inputs", () => {
    expect(computeFit({ top: 95.6, parentPad: Number.NaN, barH: -4, keepPadding: false })).toEqual({ top: 96, clearance: 0, pad: 0 })
  })
})

describe("fitStyle", () => {
  it("fills to the viewport edge when nothing is to clear", () => {
    expect(fitStyle({ top: 96, clearance: 0, pad: 24 })).toEqual({ height: "calc(100dvh - 96px)", marginBottom: -24 })
  })
  it("stops above a 63px bar and keeps the document one viewport tall", () => {
    expect(fitStyle({ top: 96, clearance: 63, pad: 24 })).toEqual({ height: "calc(100dvh - 159px)", marginBottom: 39 })
  })
  it("padding equal to clearance needs no margin", () => {
    expect(fitStyle({ top: 96, clearance: 88, pad: 88 })).toEqual({ height: "calc(100dvh - 184px)", marginBottom: 0 })
  })
})

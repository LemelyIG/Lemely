import { describe, expect, it } from "vitest"

import { downscaleLuma, frameDelta } from "@/lib/scanner/luma"

/** Solid-colour RGBA buffer, width x height. */
function solidRgba(width: number, height: number, r: number, g: number, b: number): Uint8ClampedArray {
  const data = new Uint8ClampedArray(width * height * 4)
  for (let i = 0; i < width * height; i++) {
    data[i * 4] = r
    data[i * 4 + 1] = g
    data[i * 4 + 2] = b
    data[i * 4 + 3] = 255
  }
  return data
}

describe("downscaleLuma", () => {
  it("converts RGBA to greyscale via ITU-R BT.601 weights", () => {
    const rgba = solidRgba(4, 4, 10, 20, 30)
    const result = downscaleLuma(rgba, 4, 4, 2)
    const expected = 0.299 * 10 + 0.587 * 20 + 0.114 * 30
    expect(result.width).toBe(2)
    expect(result.height).toBe(2)
    for (const value of result.data) {
      expect(value).toBeCloseTo(expected, 3)
    }
  })

  it("preserves aspect ratio when downscaling a non-square frame", () => {
    const rgba = solidRgba(80, 40, 100, 100, 100)
    const result = downscaleLuma(rgba, 80, 40, 20)
    expect(result.width).toBe(20)
    expect(result.height).toBe(10)
  })

  it("never upscales beyond the source width", () => {
    const rgba = solidRgba(10, 10, 50, 50, 50)
    const result = downscaleLuma(rgba, 10, 10, 320)
    expect(result.width).toBe(10)
  })
})

describe("frameDelta", () => {
  it("is 0 for two identical frames", () => {
    const a = new Float32Array([10, 20, 30, 40])
    const b = new Float32Array([10, 20, 30, 40])
    expect(frameDelta(a, b)).toBe(0)
  })

  it("is greater than 0 when a frame shifts by a small amount", () => {
    const a = new Float32Array([10, 20, 30, 40])
    const b = new Float32Array([11, 21, 31, 41])
    expect(frameDelta(a, b)).toBeGreaterThan(0)
    expect(frameDelta(a, b)).toBeCloseTo(1, 5)
  })

  it("is bounded by 255 (both buffers already 0..255 luma)", () => {
    const a = new Float32Array([0, 0, 0])
    const b = new Float32Array([255, 255, 255])
    expect(frameDelta(a, b)).toBe(255)
  })
})

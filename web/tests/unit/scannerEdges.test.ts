import { describe, expect, it } from "vitest"

import { sobelMagnitude } from "@/lib/scanner/edges"

/** A flat luma buffer, one value everywhere. */
function flatLuma(width: number, height: number, value: number): Float32Array {
  return new Float32Array(width * height).fill(value)
}

/** A white rectangle on a black field, inclusive bounds. */
function rectangleLuma(
  width: number,
  height: number,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): Float32Array {
  const data = new Float32Array(width * height)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      data[y * width + x] = x >= x0 && x <= x1 && y >= y0 && y <= y1 ? 255 : 0
    }
  }
  return data
}

describe("sobelMagnitude", () => {
  it("is 0 everywhere for a flat frame", () => {
    const luma = flatLuma(20, 20, 128)
    const edges = sobelMagnitude(luma, 20, 20)
    expect(Array.from(edges).every((v) => v === 0)).toBe(true)
  })

  it("peaks on the border of a rectangle and stays low in the interior/exterior", () => {
    const width = 30
    const height = 30
    const luma = rectangleLuma(width, height, 8, 8, 21, 21)
    const edges = sobelMagnitude(luma, width, height)

    // Well inside the rectangle: flat, so no gradient.
    expect(edges[15 * width + 15]).toBe(0)
    // Well outside the rectangle: flat, so no gradient.
    expect(edges[2 * width + 2]).toBe(0)
    // On the rectangle's left border: a strong horizontal gradient.
    expect(edges[15 * width + 8]).toBeGreaterThan(200)
    // On the rectangle's top border: a strong vertical gradient.
    expect(edges[8 * width + 15]).toBeGreaterThan(200)
  })

  it("leaves a 0 border (no full 3x3 neighbourhood available)", () => {
    const width = 10
    const height = 10
    const luma = rectangleLuma(width, height, 0, 0, 9, 9)
    const edges = sobelMagnitude(luma, width, height)
    for (let x = 0; x < width; x++) {
      expect(edges[x]).toBe(0)
      expect(edges[(height - 1) * width + x]).toBe(0)
    }
  })

  it("returns an all-zero buffer for frames smaller than the 3x3 kernel", () => {
    const luma = new Float32Array([1, 2, 3, 4])
    const edges = sobelMagnitude(luma, 2, 2)
    expect(Array.from(edges).every((v) => v === 0)).toBe(true)
  })
})

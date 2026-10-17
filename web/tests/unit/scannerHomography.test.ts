import { describe, expect, it } from "vitest"

import type { Quad } from "@/lib/scanner/quad"
import { homographyFromQuad, warpToRect } from "@/lib/scanner/homography"

/** Applies a row-major 3x3 homography to a point. */
function apply(m: Float64Array, x: number, y: number): [number, number] {
  const w = m[6] * x + m[7] * y + m[8]
  return [(m[0] * x + m[1] * y + m[2]) / w, (m[3] * x + m[4] * y + m[5]) / w]
}

describe("homographyFromQuad", () => {
  it("maps an axis-aligned rectangle's own corners exactly onto the destination rect", () => {
    const src: Quad = [
      { x: 10, y: 20 },
      { x: 110, y: 20 },
      { x: 110, y: 220 },
      { x: 10, y: 220 },
    ]
    const H = homographyFromQuad(src, 100, 200)
    const expected: [number, number][] = [
      [0, 0],
      [100, 0],
      [100, 200],
      [0, 200],
    ]
    src.forEach((point, i) => {
      const [x, y] = apply(H, point.x, point.y)
      expect(x).toBeCloseTo(expected[i][0], 6)
      expect(y).toBeCloseTo(expected[i][1], 6)
    })
  })

  it("maps a skewed (non-rectangular) quad's corners exactly too", () => {
    const src: Quad = [
      { x: 12, y: 8 },
      { x: 150, y: 20 },
      { x: 140, y: 190 },
      { x: 5, y: 180 },
    ]
    const H = homographyFromQuad(src, 80, 120)
    const expected: [number, number][] = [
      [0, 0],
      [80, 0],
      [80, 120],
      [0, 120],
    ]
    src.forEach((point, i) => {
      const [x, y] = apply(H, point.x, point.y)
      expect(x).toBeCloseTo(expected[i][0], 4)
      expect(y).toBeCloseTo(expected[i][1], 4)
    })
  })
})

describe("warpToRect", () => {
  it("warps a solid-colour quad into a solid-colour output", () => {
    const width = 10
    const height = 10
    const rgba = new Uint8ClampedArray(width * height * 4)
    for (let i = 0; i < width * height; i++) {
      rgba[i * 4] = 120
      rgba[i * 4 + 1] = 60
      rgba[i * 4 + 2] = 200
      rgba[i * 4 + 3] = 255
    }
    const quad: Quad = [
      { x: 0, y: 0 },
      { x: 9, y: 0 },
      { x: 9, y: 9 },
      { x: 0, y: 9 },
    ]
    const out = warpToRect(rgba, width, height, quad, { width: 6, height: 6 })
    expect(out.length).toBe(6 * 6 * 4)
    for (let i = 0; i < 6 * 6; i++) {
      expect(out[i * 4]).toBeCloseTo(120, 0)
      expect(out[i * 4 + 1]).toBeCloseTo(60, 0)
      expect(out[i * 4 + 2]).toBeCloseTo(200, 0)
      expect(out[i * 4 + 3]).toBeCloseTo(255, 0)
    }
  })

  it("produces an output image sized exactly out.width x out.height", () => {
    const width = 20
    const height = 20
    const rgba = new Uint8ClampedArray(width * height * 4).fill(255)
    const quad: Quad = [
      { x: 2, y: 2 },
      { x: 17, y: 2 },
      { x: 17, y: 17 },
      { x: 2, y: 17 },
    ]
    const out = warpToRect(rgba, width, height, quad, { width: 8, height: 12 })
    expect(out.length).toBe(8 * 12 * 4)
  })
})

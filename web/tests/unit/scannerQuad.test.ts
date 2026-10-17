import { describe, expect, it } from "vitest"

import { sobelMagnitude } from "@/lib/scanner/edges"
import { findDocumentQuad, orderQuad, type Point } from "@/lib/scanner/quad"

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

function closeTo(point: Point, expected: Point, tolerance = 2) {
  expect(Math.abs(point.x - expected.x)).toBeLessThanOrEqual(tolerance)
  expect(Math.abs(point.y - expected.y)).toBeLessThanOrEqual(tolerance)
}

describe("findDocumentQuad", () => {
  it("finds a white rectangle's corners within 2px, ordered TL/TR/BR/BL", () => {
    const width = 60
    const height = 60
    const luma = rectangleLuma(width, height, 15, 15, 44, 44)
    const edges = sobelMagnitude(luma, width, height)

    const quad = findDocumentQuad(edges, width, height)
    expect(quad).not.toBeNull()
    const [tl, tr, br, bl] = quad!
    closeTo(tl, { x: 15, y: 15 })
    closeTo(tr, { x: 44, y: 15 })
    closeTo(br, { x: 44, y: 44 })
    closeTo(bl, { x: 15, y: 44 })
  })

  it("returns null when nothing crosses the edge threshold", () => {
    const edges = new Float32Array(40 * 40)
    expect(findDocumentQuad(edges, 40, 40)).toBeNull()
  })

  it("returns null when the found region is below minAreaRatio", () => {
    const width = 100
    const height = 100
    // A tiny 5x5 rectangle: far under the default 0.2 area ratio.
    const luma = rectangleLuma(width, height, 40, 40, 45, 45)
    const edges = sobelMagnitude(luma, width, height)
    expect(findDocumentQuad(edges, width, height)).toBeNull()
  })

  it("honours a custom minAreaRatio", () => {
    const width = 100
    const height = 100
    const luma = rectangleLuma(width, height, 40, 40, 45, 45)
    const edges = sobelMagnitude(luma, width, height)
    expect(findDocumentQuad(edges, width, height, { minAreaRatio: 0.001 })).not.toBeNull()
  })
})

describe("orderQuad", () => {
  it("orders four points TL, TR, BR, BL regardless of input order", () => {
    const tl = { x: 0, y: 0 }
    const tr = { x: 10, y: 0 }
    const br = { x: 10, y: 10 }
    const bl = { x: 0, y: 10 }

    expect(orderQuad([br, bl, tr, tl])).toEqual([tl, tr, br, bl])
    expect(orderQuad([tl, tr, br, bl])).toEqual([tl, tr, br, bl])
    expect(orderQuad([bl, tl, br, tr])).toEqual([tl, tr, br, bl])
  })

  it("orders a skewed quad by sum/difference of coordinates", () => {
    const tl = { x: 5, y: 2 }
    const tr = { x: 40, y: 5 }
    const br = { x: 38, y: 45 }
    const bl = { x: 3, y: 42 }

    expect(orderQuad([br, tl, bl, tr])).toEqual([tl, tr, br, bl])
  })
})

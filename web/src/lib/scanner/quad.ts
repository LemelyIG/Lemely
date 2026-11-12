/*
 * Task 8 (B5b) · scanner pipeline, stage 3: document quad from edge magnitude.
 *
 * No contour tracing, no Hough transform: the accuracy floor this hand-rolled
 * pipeline commits to (DESIGN.md §15) is a rectangular sheet of paper on a
 * contrasting surface, filling at least `minAreaRatio` of the frame — and for
 * that case the axis-aligned bounding box of the thresholded edge pixels IS
 * the document's quad (its four corners sit exactly on that box). A genuinely
 * skewed/rotated photo degrades to a bounding box that over-includes the
 * corners rather than a wrong shape entirely, which `warpToRect`'s bilinear
 * sampling tolerates far better than a false "no document found".
 */

export interface Point {
  x: number
  y: number
}

export type Quad = [Point, Point, Point, Point]

export interface FindQuadOptions {
  /** Edge-magnitude values above this count as a document boundary. */
  threshold?: number
  /** Minimum area of the found quad, as a fraction of the frame. */
  minAreaRatio?: number
}

const DEFAULT_THRESHOLD = 40
const DEFAULT_MIN_AREA_RATIO = 0.2

export function findDocumentQuad(
  edges: Float32Array,
  width: number,
  height: number,
  options?: FindQuadOptions,
): Quad | null {
  const threshold = options?.threshold ?? DEFAULT_THRESHOLD
  const minAreaRatio = options?.minAreaRatio ?? DEFAULT_MIN_AREA_RATIO

  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  let found = false

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (edges[y * width + x] <= threshold) continue
      found = true
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y
    }
  }

  if (!found) return null

  const area = (maxX - minX) * (maxY - minY)
  if (area / (width * height) < minAreaRatio) return null

  return orderQuad([
    { x: minX, y: minY },
    { x: maxX, y: minY },
    { x: maxX, y: maxY },
    { x: minX, y: maxY },
  ])
}

/**
 * Orders four points TL, TR, BR, BL regardless of input order. TL has the
 * smallest `x+y`, BR the largest; of the remaining two, TR has the larger
 * `x-y` and BL the smaller — the standard sum/difference corner ordering.
 */
export function orderQuad(points: readonly Point[]): Quad {
  const bySum = [...points].sort((a, b) => a.x + a.y - (b.x + b.y))
  const byDiff = [...points].sort((a, b) => a.x - a.y - (b.x - b.y))

  const tl = bySum[0]
  const br = bySum[bySum.length - 1]
  const bl = byDiff[0]
  const tr = byDiff[byDiff.length - 1]

  return [tl, tr, br, bl]
}

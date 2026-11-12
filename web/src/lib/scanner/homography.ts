import type { Point, Quad } from "./quad"

/*
 * Task 8 (B5b) · scanner pipeline, stage 4: perspective correction.
 *
 * `homographyFromQuad` solves the classic 4-point DLT (direct linear
 * transform) for a projective mapping from an arbitrary quad to an
 * axis-aligned rectangle — 8 unknowns (h33 fixed to 1), 8 equations, one per
 * point's x and y. `warpToRect` inverts that mapping (rectangle -> quad) and
 * samples the source image backwards, pixel by pixel, so every output pixel
 * is filled (a forward warp would leave gaps wherever the quad is smaller
 * than the source region it maps from).
 */

/** Row-major 3x3: [h11,h12,h13, h21,h22,h23, h31,h32,h33]. */
type Matrix3x3 = Float64Array

function solveLinearSystem(coefficients: number[][], constants: number[]): number[] {
  const n = constants.length
  const augmented = coefficients.map((row, i) => [...row, constants[i]])

  for (let col = 0; col < n; col++) {
    let pivotRow = col
    for (let r = col + 1; r < n; r++) {
      if (Math.abs(augmented[r][col]) > Math.abs(augmented[pivotRow][col])) pivotRow = r
    }
    const tmp = augmented[col]
    augmented[col] = augmented[pivotRow]
    augmented[pivotRow] = tmp

    const pivot = augmented[col][col]
    for (let c = col; c <= n; c++) augmented[col][c] /= pivot

    for (let r = 0; r < n; r++) {
      if (r === col) continue
      const factor = augmented[r][col]
      if (factor === 0) continue
      for (let c = col; c <= n; c++) augmented[r][c] -= factor * augmented[col][c]
    }
  }

  return augmented.map((row) => row[n])
}

function computeHomography(src: readonly Point[], dst: readonly Point[]): Matrix3x3 {
  const coefficients: number[][] = []
  const constants: number[] = []

  for (let i = 0; i < 4; i++) {
    const { x, y } = src[i]
    const { x: u, y: v } = dst[i]
    coefficients.push([x, y, 1, 0, 0, 0, -u * x, -u * y])
    constants.push(u)
    coefficients.push([0, 0, 0, x, y, 1, -v * x, -v * y])
    constants.push(v)
  }

  const h = solveLinearSystem(coefficients, constants)
  return new Float64Array([...h, 1])
}

/** Maps `src` (TL, TR, BR, BL) onto the rectangle (0,0)..(dstWidth,dstHeight). */
export function homographyFromQuad(src: Quad, dstWidth: number, dstHeight: number): Matrix3x3 {
  const dst: Quad = [
    { x: 0, y: 0 },
    { x: dstWidth, y: 0 },
    { x: dstWidth, y: dstHeight },
    { x: 0, y: dstHeight },
  ]
  return computeHomography(src, dst)
}

function invert3x3(m: Matrix3x3): Matrix3x3 {
  const [a, b, c, d, e, f, g, h, i] = m
  const A = e * i - f * h
  const B = f * g - d * i
  const C = d * h - e * g
  const D = c * h - b * i
  const E = a * i - c * g
  const F = b * g - a * h
  const G = b * f - c * e
  const H = c * d - a * f
  const I = a * e - b * d
  const det = a * A + b * B + c * C
  const invDet = det === 0 ? 0 : 1 / det
  return new Float64Array([
    A * invDet, D * invDet, G * invDet,
    B * invDet, E * invDet, H * invDet,
    C * invDet, F * invDet, I * invDet,
  ])
}

function applyHomography(m: Matrix3x3, x: number, y: number): [number, number] {
  const w = m[6] * x + m[7] * y + m[8]
  return [(m[0] * x + m[1] * y + m[2]) / w, (m[3] * x + m[4] * y + m[5]) / w]
}

function sampleBilinear(
  rgba: Uint8ClampedArray,
  width: number,
  height: number,
  x: number,
  y: number,
): [number, number, number, number] {
  const cx = Math.min(Math.max(x, 0), width - 1)
  const cy = Math.min(Math.max(y, 0), height - 1)
  const x0 = Math.floor(cx)
  const y0 = Math.floor(cy)
  const x1 = Math.min(x0 + 1, width - 1)
  const y1 = Math.min(y0 + 1, height - 1)
  const fx = cx - x0
  const fy = cy - y0
  const pixelIndex = (px: number, py: number) => (py * width + px) * 4

  const out: [number, number, number, number] = [0, 0, 0, 0]
  for (let ch = 0; ch < 4; ch++) {
    const v00 = rgba[pixelIndex(x0, y0) + ch]
    const v10 = rgba[pixelIndex(x1, y0) + ch]
    const v01 = rgba[pixelIndex(x0, y1) + ch]
    const v11 = rgba[pixelIndex(x1, y1) + ch]
    const top = v00 * (1 - fx) + v10 * fx
    const bottom = v01 * (1 - fx) + v11 * fx
    out[ch] = top * (1 - fy) + bottom * fy
  }
  return out
}

/**
 * Warps the `quad` region of an RGBA `width`x`height` frame into an
 * `out.width`x`out.height` rectangular RGBA buffer, via inverse-mapped
 * bilinear sampling (backward warp — every destination pixel is filled).
 */
export function warpToRect(
  rgba: Uint8ClampedArray,
  width: number,
  height: number,
  quad: Quad,
  out: { width: number; height: number },
): Uint8ClampedArray {
  const forward = homographyFromQuad(quad, out.width, out.height)
  const inverse = invert3x3(forward)
  const result = new Uint8ClampedArray(out.width * out.height * 4)

  for (let oy = 0; oy < out.height; oy++) {
    for (let ox = 0; ox < out.width; ox++) {
      const [sx, sy] = applyHomography(inverse, ox, oy)
      const [r, g, b, a] = sampleBilinear(rgba, width, height, sx, sy)
      const idx = (oy * out.width + ox) * 4
      result[idx] = r
      result[idx + 1] = g
      result[idx + 2] = b
      result[idx + 3] = a
    }
  }

  return result
}

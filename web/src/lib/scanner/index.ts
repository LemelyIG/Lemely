/*
 * Task 8 (B5b) · scanner: the lazy entry point.
 *
 * `CameraCapture.tsx` imports this module with `await import("@/lib/scanner")`
 * once the camera stream starts, not at module load — the hand-rolled Sobel +
 * quad + homography pipeline here is ~3-4KB gzipped in its own chunk, and
 * every reader who lands on `CorrectPaper` but never opens the camera (the
 * file-picker path) should not pay for it. See DESIGN.md §15's "Scanner"
 * paragraph for the bundle-size reasoning against `opencv.js`.
 *
 * `analyseFrame`/`correctPerspective` are thin, canvas-shaped wrappers over
 * the pure pipeline (`luma.ts`, `edges.ts`, `quad.ts`, `homography.ts`,
 * `stability.ts`) — the pure functions are what the unit tests exercise
 * directly (no DOM/canvas needed, per D3.20); these two exist only to save
 * `CameraCapture.tsx` from re-deriving the same five-step pipeline at every
 * call site.
 */

import { downscaleLuma, frameDelta } from "./luma"
import { sobelMagnitude } from "./edges"
import { findDocumentQuad, type Quad } from "./quad"
import { warpToRect } from "./homography"

export { stabilityDecision, type StabilityOptions } from "./stability"
export { torchSupported, setTorch } from "./torch"
export type { Point, Quad } from "./quad"

/** Width of the internal luma buffer everything below runs on. */
export const ANALYSIS_WIDTH = 320

export interface FrameAnalysis {
  /** Document quad, already scaled to the `width`x`height` passed in — never the internal analysis resolution. */
  quad: Quad | null
  /** Mean luma delta vs. `previous`, 0..255 (255 when there is no `previous` yet). */
  delta: number
  /** This frame's downscaled luma buffer. Feed it back in as `previous` on the next call. */
  luma: Float32Array
}

/**
 * Analyses one frame already drawn onto `ctx` (a `width`x`height` canvas —
 * typically the rAF loop's small analysis canvas, not the full-resolution
 * capture canvas): downscales to `ANALYSIS_WIDTH`, runs Sobel + quad-find,
 * and measures motion against `previous`.
 */
export function analyseFrame(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  previous: Float32Array | null,
): FrameAnalysis {
  const imageData = ctx.getImageData(0, 0, width, height)
  const luma = downscaleLuma(imageData.data, width, height, ANALYSIS_WIDTH)
  const edges = sobelMagnitude(luma.data, luma.width, luma.height)
  const found = findDocumentQuad(edges, luma.width, luma.height)
  const delta = previous ? frameDelta(luma.data, previous) : 255

  const scaleX = width / luma.width
  const scaleY = height / luma.height
  const quad: Quad | null = found
    ? (found.map((point) => ({ x: point.x * scaleX, y: point.y * scaleY })) as Quad)
    : null

  return { quad, delta, luma: luma.data }
}

/**
 * Perspective-corrects the region `quad` (in `ctx`'s own `width`x`height`
 * coordinate space) out of the frame drawn on `ctx`, warped to that same
 * `width`x`height` output size.
 */
export function correctPerspective(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  quad: Quad,
): ImageData {
  const imageData = ctx.getImageData(0, 0, width, height)
  const warped = warpToRect(imageData.data, width, height, quad, { width, height })
  // `warpToRect` returns a `Uint8ClampedArray` typed over `ArrayBufferLike`
  // (may include `SharedArrayBuffer`), which the `ImageData` constructor
  // rejects at the type level. Copy into a plain ArrayBuffer-backed view —
  // the same pattern `lib/pdf/assemblePages.ts` uses for the analogous
  // `pdf-lib` mismatch.
  const buffer = new ArrayBuffer(warped.byteLength)
  new Uint8ClampedArray(buffer).set(warped)
  return new ImageData(new Uint8ClampedArray(buffer), width, height)
}

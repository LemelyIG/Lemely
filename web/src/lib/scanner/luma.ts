/*
 * Task 8 (B5b) · scanner pipeline, stage 1: greyscale downscale + frame delta.
 *
 * Every later stage (Sobel, quad-find, stability) runs on a small greyscale
 * buffer rather than the full RGBA camera frame — a 320px-wide luma buffer
 * keeps `sobelMagnitude`/`findDocumentQuad` (both O(width*height)) cheap
 * enough to run once per few rAF ticks on a phone. `downscaleLuma` does both
 * conversions in one pass (nearest-neighbour sampling into the target grid,
 * ITU-R BT.601 luma weights) so the rAF loop never allocates a full-size
 * intermediate buffer.
 */

export interface LumaFrame {
  data: Float32Array
  width: number
  height: number
}

/**
 * Downscale an RGBA frame to `targetWidth` (height scaled to preserve
 * aspect ratio) and convert to greyscale luma (0..255). Nearest-neighbour
 * sampling: bilinear would cost more per pixel for no benefit here — the
 * output only ever feeds edge detection and a coarse motion delta, neither
 * of which needs sub-pixel accuracy.
 */
export function downscaleLuma(
  rgba: Uint8ClampedArray,
  width: number,
  height: number,
  targetWidth: number,
): LumaFrame {
  const clampedTargetWidth = Math.max(1, Math.min(targetWidth, width))
  const targetHeight = Math.max(1, Math.round((height * clampedTargetWidth) / width))
  const data = new Float32Array(clampedTargetWidth * targetHeight)

  for (let ty = 0; ty < targetHeight; ty++) {
    const sy = Math.min(height - 1, Math.floor((ty * height) / targetHeight))
    for (let tx = 0; tx < clampedTargetWidth; tx++) {
      const sx = Math.min(width - 1, Math.floor((tx * width) / clampedTargetWidth))
      const srcIdx = (sy * width + sx) * 4
      const r = rgba[srcIdx]
      const g = rgba[srcIdx + 1]
      const b = rgba[srcIdx + 2]
      data[ty * clampedTargetWidth + tx] = 0.299 * r + 0.587 * g + 0.114 * b
    }
  }

  return { data, width: clampedTargetWidth, height: targetHeight }
}

/**
 * Mean absolute difference between two same-shaped luma buffers, 0..255.
 * `stability.ts` reads a rolling window of these to decide whether the
 * frame in front of the camera has stopped moving.
 */
export function frameDelta(a: Float32Array, b: Float32Array): number {
  const length = Math.min(a.length, b.length)
  if (length === 0) return 0
  let sum = 0
  for (let i = 0; i < length; i++) {
    sum += Math.abs(a[i] - b[i])
  }
  return sum / length
}

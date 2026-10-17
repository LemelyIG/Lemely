/*
 * Task 8 (B5b) · scanner pipeline, stage 2: Sobel edge magnitude.
 *
 * The classic 3x3 Sobel kernels, run over the luma buffer `downscaleLuma`
 * produced. Border pixels (no full 3x3 neighbourhood) are left at 0 rather
 * than clamped/wrapped — a document photographed close-up fills most of the
 * frame, so a one-pixel-wide dead border at the analysis resolution (320px)
 * costs nothing `findDocumentQuad`'s bounding-box scan would otherwise use.
 */

const KERNEL_X = [-1, 0, 1, -2, 0, 2, -1, 0, 1]
const KERNEL_Y = [-1, -2, -1, 0, 0, 0, 1, 2, 1]

export function sobelMagnitude(luma: Float32Array, width: number, height: number): Float32Array {
  const out = new Float32Array(width * height)
  if (width < 3 || height < 3) return out

  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      let gx = 0
      let gy = 0
      let k = 0
      for (let ky = -1; ky <= 1; ky++) {
        for (let kx = -1; kx <= 1; kx++) {
          const sample = luma[(y + ky) * width + (x + kx)]
          gx += sample * KERNEL_X[k]
          gy += sample * KERNEL_Y[k]
          k += 1
        }
      }
      out[y * width + x] = Math.sqrt(gx * gx + gy * gy)
    }
  }

  return out
}

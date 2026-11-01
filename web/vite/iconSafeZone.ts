/*
 * Maskable-icon safe-zone arithmetic.
 *
 * Android crops a maskable icon to whatever shape the launcher wants (circle,
 * squircle, teardrop) and only guarantees the central circle of diameter 0.8w.
 * A drawn rectangle of width x height (as fractions of the icon) is fully
 * inside that circle only when hypot(width, height) <= 0.8, with the rectangle
 * centred on the icon. The artwork (clip and "m", see `appIcon.ts`) is not
 * square and not centred on its own artboard, so its drawn bounds are measured
 * from the rendered alpha rather than assumed, and the maskable icon centres
 * those bounds before scaling.
 *
 * `scripts/generate_icons.mjs` and `tests/unit/brandTokens.test.ts` both
 * import this module so the arithmetic and the constant it guards live in one
 * place.
 */

import sharp from "sharp"

/**
 * How much the artwork is scaled, relative to its native size on the 100 unit
 * artboard, when it is drawn into the maskable icon.
 *
 * It must stay under `maxMaskableScale` for the measured bounds. The value is
 * set with a margin below that ceiling for launcher shapes that crop harder
 * than a circle.
 */
export const MASKABLE_SCALE = 0.72

export interface DrawnBounds {
  /** Left edge, as a fraction of the artboard width. */
  left: number
  /** Top edge, as a fraction of the artboard height. */
  top: number
  width: number
  height: number
}

/**
 * The artwork's drawn bounds, as fractions of its artboard, measured from the
 * rendered alpha rather than read off the coordinates.
 */
export async function measureDrawnBounds(svg: Buffer | Uint8Array): Promise<DrawnBounds> {
  const N = 512
  const { data } = await sharp(svg, { density: 384 })
    .resize(N, N)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true })
  let left = N
  let top = N
  let right = -1
  let bottom = -1
  for (let y = 0; y < N; y += 1) {
    for (let x = 0; x < N; x += 1) {
      // 8/255, so a stroke's outermost antialiased fringe does not count as ink.
      if (data[(y * N + x) * 4 + 3] <= 8) continue
      if (x < left) left = x
      if (x > right) right = x
      if (y < top) top = y
      if (y > bottom) bottom = y
    }
  }
  return { left: left / N, top: top / N, width: (right - left + 1) / N, height: (bottom - top + 1) / N }
}

/**
 * The safe-zone ceiling `MASKABLE_SCALE` must never exceed, for artwork with
 * the given drawn bounds. See this module's own docstring for the arithmetic.
 */
export function maxMaskableScale(bounds: Pick<DrawnBounds, "width" | "height">): number {
  return 0.8 / Math.hypot(bounds.width, bounds.height)
}

/**
 * The SVG transform (on a 100 unit artboard) that scales the artwork by `scale`
 * and centres its drawn bounds on the artboard centre.
 */
export function maskableTransform(bounds: DrawnBounds, scale: number): string {
  const cx = (bounds.left + bounds.width / 2) * 100
  const cy = (bounds.top + bounds.height / 2) * 100
  const tx = 50 - cx * scale
  const ty = 50 - cy * scale
  return `translate(${tx.toFixed(3)} ${ty.toFixed(3)}) scale(${scale})`
}

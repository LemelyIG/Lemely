/*
 * Icon safe-zone constants and the mark-shape-aware Android maskable-icon
 * ceiling.
 *
 * `MAX_MASKABLE_SCALE` cannot be a fixed constant once the mark's drawn
 * extent isn't a perfect square: Android's guaranteed-visible region on a
 * maskable icon is a circle of diameter 0.8w centred on the icon, so a drawn
 * rectangle of width x height (as fractions of the icon) is fully inside it
 * only when hypot(width, height) <= 0.8. A square mark's diagonal is
 * width*sqrt(2), which is why this used to be a fixed `0.8 / sqrt(2)` — but
 * the mark is an open notebook (landscape), so its own drawn extent has to
 * be measured against the real SVG, not assumed.
 *
 * `scripts/generate_icons.mjs` and `tests/unit/brandTokens.test.ts` both
 * import this module so the safe-zone arithmetic and the constants it
 * guards live in one place.
 */

import sharp from "sharp"

/**
 * How much of a square icon's width the mark spans.
 *
 * `0.72` puts the drawn mark at about 64% of the icon's width and 49% of its
 * height — a normal figure for an app icon, and one that still leaves the
 * outer edge clear on a rounded-rectangle mask.
 */
export const SQUARE_SCALE = 0.72

/**
 * How much of a maskable icon's width the mark spans.
 *
 * `0.6` against a measured ceiling (see `maxMaskableScale`) — the margin is
 * for launcher shapes that crop harder than a circle.
 */
export const MASKABLE_SCALE = 0.6

export interface DrawnExtent {
  width: number
  height: number
}

/**
 * The mark's drawn extent, as a fraction of its artboard, measured from the
 * rendered alpha rather than read off the coordinates or assumed square.
 */
export async function measureDrawnExtent(markSvg: Buffer | Uint8Array): Promise<DrawnExtent> {
  const N = 512
  const { data } = await sharp(markSvg, { density: 384 })
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
  return { width: (right - left + 1) / N, height: (bottom - top + 1) / N }
}

/**
 * The safe-zone ceiling `MASKABLE_SCALE` must never exceed, for a mark with
 * the given drawn extent. See this module's own docstring for the arithmetic.
 */
export function maxMaskableScale(extent: DrawnExtent): number {
  return 0.8 / Math.hypot(extent.width, extent.height)
}

/*
 * The Lemely app icon, as data. This is the single source for the favicon (SVG
 * and ICO), the PWA icons, the Apple touch icon, the store icon, the maskable
 * icon, the iOS splash screens, the shortcut icons and the Open Graph card.
 *
 * It is the primary icon from the Lemely Brand Guidelines (v5 Abyss, section
 * "APP ICON"): an Abyss field, the paper-clip drawn in Tide, and a white
 * lowercase "m". The guidelines' own rules, kept here:
 *
 * - The clip stroke is always 5 (in the clip's own coordinates, before the
 *   group scale below), never thinner at small sizes. The guidelines show this
 *   same icon at 16px, so the favicon is this icon and not a simplified cut.
 * - The clip is Tide (#7fb8e0) on this dark field. Abyss is for light
 *   backgrounds and is never used on dark.
 *
 * The "m" is Bricolage Grotesque 600 in the guidelines. It is stored below as
 * an outline path, not as text, so rendering never depends on a font being
 * installed. librsvg (and so sharp) cannot load the project's woff2 files, and
 * a missing font would silently fall back to a system face in a binary nobody
 * diffs. Origin of the path: `bricolage-grotesque-latin-opsz-normal.woff2` from
 * `@fontsource-variable/bricolage-grotesque`, instanced at opsz 52 and wght 600
 * (the 52 matches the guidelines' font-size, which CSS optical sizing would
 * also map to opsz 52), glyph "m", scaled by 52/1000 and placed with its
 * advance centred on x=68 and its baseline on y=78. That is exactly where the
 * guidelines' `<text x="68" y="78" text-anchor="middle" font-size="52">` puts it.
 * It was converted once with fontTools (`instantiateVariableFont`, then an
 * SVGPathPen through a flip-and-scale transform). To regenerate it, redo that
 * conversion; nothing else in the repo needs fontTools.
 */

/** Abyss, the icon field. From the brand guidelines. */
export const ABYSS = "#042f4f"
/** Tide, the clip on a dark field. From the brand guidelines. */
export const TIDE = "#7fb8e0"

/** The paper-clip, in its own coordinates. Stroke width 5, round caps. */
export const CLIP_PATH = "M58 34 V72 A8 8 0 0 1 42 72 V20 A14 14 0 0 1 70 20 V78 A18 18 0 0 1 34 78 V36"

/** Placement of the clip inside the 100x100 artboard. */
export const CLIP_TRANSFORM = "translate(-8 16) scale(0.66)"

/** The letter "m", Bricolage Grotesque 600, as a filled outline path. See the header. */
export const M_PATH =
  "M47.89 78V62.47L47.86 50.84H53.43L53.16 60.83H53.88Q54.43 57.1 55.56 54.75Q56.69 52.39 58.45 51.26Q60.21 50.13 62.61 50.13Q65.18 50.13 66.81 51.37Q68.43 52.62 69.24 54.99Q70.04 57.36 70.05 60.79H70.71Q71.24 57.1 72.44 54.75Q73.65 52.4 75.51 51.26Q77.37 50.13 79.81 50.13Q81.97 50.13 83.58 50.96Q85.19 51.79 86.28 53.43Q87.38 55.07 87.92 57.54Q88.45 60.01 88.45 63.27V78H81.86V64.04Q81.86 61.3 81.4 59.49Q80.94 57.69 79.99 56.81Q79.04 55.92 77.55 55.92Q75.73 55.92 74.37 57.27Q73.01 58.61 72.23 61.08Q71.45 63.55 71.37 66.95V78H64.93V64.09Q64.93 61.32 64.45 59.52Q63.97 57.72 63.01 56.82Q62.05 55.92 60.58 55.92Q58.76 55.92 57.42 57.23Q56.08 58.54 55.3 61.03Q54.53 63.52 54.46 67V78Z"

/** Clip and "m" only, on a 100x100 artboard, no field. Used to measure the drawn extent. */
export function appIconContent(transform?: string): string {
  const inner =
    `<g transform="${CLIP_TRANSFORM}"><path d="${CLIP_PATH}" fill="none" stroke="${TIDE}" stroke-width="5" stroke-linecap="round"/></g>` +
    `<path d="${M_PATH}" fill="#ffffff"/>`
  return transform ? `<g transform="${transform}">${inner}</g>` : inner
}

export type AppIconField =
  /** The guidelines' rounded tile, transparent corners. For favicons and "any" icons. */
  | "rounded"
  /** Full-bleed Abyss square, no transparency. For surfaces that apply their own mask. */
  | "full"

/**
 * The whole icon as a standalone SVG string (100x100 viewBox).
 *
 * `field: "rounded"` is byte-for-byte the guidelines' icon. `field: "full"` is
 * the same artwork on a square that reaches the artboard edge, for the Apple
 * touch icon, the store icon and the maskable icon, where the OS rounds or
 * crops the corners itself and transparent corners would show as black.
 * `contentTransform` repositions the artwork, which only the maskable icon needs.
 */
export function appIconSvg(field: AppIconField = "rounded", contentTransform?: string): string {
  const rect =
    field === "rounded"
      ? `<rect x="1" y="1" width="98" height="98" rx="24" fill="${ABYSS}"/>`
      : `<rect width="100" height="100" fill="${ABYSS}"/>`
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">${rect}${appIconContent(contentTransform)}</svg>`
}

/*
 * The iOS splash-screen matrix (packet B1, `no-ios-splash-screens`).
 *
 * ── Why this exists ──────────────────────────────────────────────────────
 *
 * DESIGN.md §12's three loading tiers are a promise about what a reader sees
 * between navigating and the app painting — but iOS never asks the pre-mount
 * shell (`index.html`, `vite/preMountShell.ts`) that question in the first
 * place. Safari on iOS, and an installed PWA launched from the home screen,
 * paint a blank white rectangle over the whole boot window and only replace
 * it once the app's own JS has run — unless the page's `<head>` carries an
 * `apple-touch-startup-image` link matching the device's exact physical
 * size, dpr and orientation. Nothing else on this platform reaches that
 * window: not the pre-mount shell (loaded, but never shown), not tier 1
 * (never reached), nothing.
 *
 * ── Why sixteen device entries rather than one image ────────────────────
 *
 * Apple's technique keys entirely off the media query, not off responsive
 * sizing: an image sized for one device is either letterboxed or simply not
 * shown for any other, so a single generic splash covers exactly one screen
 * size and dpr and leaves every other iPhone and iPad with the blank
 * rectangle this file exists to remove. `SPLASHES` is the fixed matrix
 * `scripts/generate_icons.mjs` renders one image per (two, counting
 * orientation) and `splashLinkTags()` (below) turns into markup.
 *
 * `width`/`height` are each device's CSS-pixel (logical) portrait
 * dimensions — the same numbers Apple's own HIG and Safari's media-query
 * matching use — and `dpr` its device pixel ratio. The *media query* always
 * states the portrait `width`/`height` pair regardless of orientation
 * (that's the pair Safari's `device-width`/`device-height` actually match
 * against); only the *image's own pixel dimensions* swap for landscape.
 * `splashLinks.ts` reads this module to substitute `%LEMELY_SPLASH_LINKS%`
 * in `index.html`, the same placeholder-substitution shape `themeColor.ts`
 * and `preMountShell.ts` already use for build-time-only values.
 */

export interface SplashDevice {
  /** A human-readable label for the device family this size covers. Not
   * used in the emitted markup — purely for anyone reading this table. */
  device: string
  /** Portrait CSS-pixel width, matched by the media query's `device-width`. */
  width: number
  /** Portrait CSS-pixel height, matched by the media query's `device-height`. */
  height: number
  /** Device pixel ratio — `-webkit-device-pixel-ratio` in the media query,
   * and the multiplier `width`/`height` scale by for the image's own pixels. */
  dpr: 2 | 3
}

export const SPLASHES: readonly SplashDevice[] = [
  { device: "iPhone 15 Pro Max, 14 Pro Max", width: 430, height: 932, dpr: 3 },
  { device: "iPhone 15 Pro, 15, 14 Pro", width: 393, height: 852, dpr: 3 },
  { device: "iPhone 14, 13, 12", width: 390, height: 844, dpr: 3 },
  { device: "iPhone 14 Plus, 13 Pro Max", width: 428, height: 926, dpr: 3 },
  { device: "iPhone 13 mini, 12 mini", width: 375, height: 812, dpr: 3 },
  { device: "iPhone 11 Pro Max, XS Max", width: 414, height: 896, dpr: 3 },
  { device: "iPhone 11, XR", width: 414, height: 896, dpr: 2 },
  { device: "iPhone 8 Plus", width: 414, height: 736, dpr: 3 },
  { device: "iPhone 8, SE", width: 375, height: 667, dpr: 2 },
  { device: "iPad Pro 12.9", width: 1024, height: 1366, dpr: 2 },
  { device: "iPad Pro 11", width: 834, height: 1194, dpr: 2 },
  { device: "iPad Air 10.9", width: 820, height: 1180, dpr: 2 },
  { device: "iPad 10.2", width: 810, height: 1080, dpr: 2 },
  { device: "iPad mini 8.3", width: 744, height: 1133, dpr: 2 },
  { device: "iPad Pro 10.5", width: 834, height: 1112, dpr: 2 },
  { device: "iPad 9.7", width: 768, height: 1024, dpr: 2 },
]

export type SplashOrientation = "portrait" | "landscape"

/** The splash PNG's own pixel dimensions for one device/orientation pair —
 * `device × dpr`, swapped for landscape. */
export function splashImagePx(
  entry: SplashDevice,
  orientation: SplashOrientation,
): { width: number; height: number } {
  const portraitWidth = Math.round(entry.width * entry.dpr)
  const portraitHeight = Math.round(entry.height * entry.dpr)
  return orientation === "portrait"
    ? { width: portraitWidth, height: portraitHeight }
    : { width: portraitHeight, height: portraitWidth }
}

/** The filename (no directory) a device/orientation pair's image is written
 * to and linked from — `<width>x<height>.png`, shared between
 * `generate_icons.mjs` (which writes the file) and `splashLinkTags` (which
 * links it), so the two cannot drift apart. */
export function splashFilename(entry: SplashDevice, orientation: SplashOrientation): string {
  const { width, height } = splashImagePx(entry, orientation)
  return `${width}x${height}.png`
}

/**
 * Every `<link rel="apple-touch-startup-image">` tag the splash matrix
 * needs — two per `SPLASHES` entry (portrait, landscape), 32 total.
 *
 * Substituted into `index.html`'s `%LEMELY_SPLASH_LINKS%` placeholder by
 * `splashLinks.ts` at build time.
 */
export function splashLinkTags(): string {
  const lines: string[] = []
  for (const entry of SPLASHES) {
    for (const orientation of ["portrait", "landscape"] as const) {
      const media =
        `screen and (device-width: ${entry.width}px) and (device-height: ${entry.height}px) ` +
        `and (-webkit-device-pixel-ratio: ${entry.dpr}) and (orientation: ${orientation})`
      lines.push(
        `<link rel="apple-touch-startup-image" media="${media}" href="/splash/${splashFilename(entry, orientation)}">`,
      )
    }
  }
  return lines.join("\n")
}

import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { SPLASHES, splashLinkTags } from "../../vite/splashScreens.ts"

/*
 * Packet B1 · iOS splash screen matrix (no-ios-splash-screens ledger row).
 *
 * iOS ignores the pre-mount shell entirely (`apple-touch-startup-image` is
 * the only mechanism it reads before its own JS engine starts) and paints a
 * blank white rectangle in its place for the whole time the app takes to
 * boot — the one platform DESIGN.md §12's loading tiers cannot reach at all,
 * because tier 1's "warm paper only" promise depends on `index.html` having
 * loaded, and this is the screen shown before that happens. `SPLASHES` is
 * the fixed matrix of every iPhone/iPad size Apple's own technique needs one
 * entry per, portrait and landscape; `splashLinkTags()` is the one place
 * that turns it into markup, read into `index.html` at build time by
 * `splashLinks.ts` (mirrors `themeColor.ts`'s placeholder-substitution
 * shape) and by `generate_icons.mjs` (mirrors that script's existing icon
 * loop) to render the PNGs.
 */

const ROOT = join(import.meta.dirname, "..", "..")

describe("SPLASHES", () => {
  it("has 16 entries (one physical device size)", () => {
    expect(SPLASHES.length).toBe(16)
  })

  it("every entry's width*dpr and height*dpr are integers", () => {
    for (const entry of SPLASHES) {
      expect(Number.isInteger(entry.width * entry.dpr), entry.device).toBe(true)
      expect(Number.isInteger(entry.height * entry.dpr), entry.device).toBe(true)
    }
  })
})

describe("splashLinkTags", () => {
  const tags = splashLinkTags()

  it("emits exactly 32 <link> tags (16 devices x 2 orientations)", () => {
    const matches = tags.match(/<link rel="apple-touch-startup-image"/g) ?? []
    expect(matches.length).toBe(32)
  })

  it("emits both a portrait and a landscape entry for every device", () => {
    for (const entry of SPLASHES) {
      const mediaPrefix = `(device-width: ${entry.width}px) and (device-height: ${entry.height}px) and (-webkit-device-pixel-ratio: ${entry.dpr})`
      expect(tags, entry.device).toContain(`${mediaPrefix} and (orientation: portrait)`)
      expect(tags, entry.device).toContain(`${mediaPrefix} and (orientation: landscape)`)
    }
  })

  it("has 32 unique hrefs", () => {
    const hrefs = [...tags.matchAll(/href="([^"]+)"/g)].map((m) => m[1])
    expect(hrefs.length).toBe(32)
    expect(new Set(hrefs).size).toBe(32)
  })

  it("swaps pixel width/height for the landscape image, keeping the media query's device-width/device-height as the portrait CSS values", () => {
    // iPhone 15 Pro Max / 14 Pro Max: 430x932 @3x -> 1290x2796 portrait,
    // 2796x1290 landscape image, same device-width/device-height pair.
    expect(tags).toContain(
      '(device-width: 430px) and (device-height: 932px) and (-webkit-device-pixel-ratio: 3) and (orientation: portrait)" href="/splash/1290x2796.png"',
    )
    expect(tags).toContain(
      '(device-width: 430px) and (device-height: 932px) and (-webkit-device-pixel-ratio: 3) and (orientation: landscape)" href="/splash/2796x1290.png"',
    )
  })
})

describe("index.html: carries the splash-links placeholder", () => {
  it("contains %LEMELY_SPLASH_LINKS%", () => {
    const html = readFileSync(join(ROOT, "index.html"), "utf8")
    expect(html).toContain("%LEMELY_SPLASH_LINKS%")
  })
})

describe("vite.config.ts: splash PNGs are excluded from the SW precache manifest", () => {
  const config = readFileSync(join(ROOT, "vite.config.ts"), "utf8")

  it("has exactly one globIgnores array", () => {
    const matches = config.match(/globIgnores/g) ?? []
    expect(matches.length).toBe(1)
  })

  it("that array contains splash/**", () => {
    const start = config.indexOf("globIgnores")
    const arrayStart = config.indexOf("[", start)
    const arrayEnd = config.indexOf("]", arrayStart)
    const block = config.slice(arrayStart, arrayEnd + 1)
    expect(block).toContain('"splash/**"')
  })
})

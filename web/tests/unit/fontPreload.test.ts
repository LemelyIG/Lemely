import { describe, expect, it } from "vitest"
import {
  CRITICAL_FACES,
  preloadTagFor,
  selectCriticalFontAssets,
} from "../../vite/fontPreload.ts"

/**
 * The font-preload gate (P6.3).
 *
 * ── What this protects, and what it deliberately does not claim ────────────
 *
 * The measured problem is small and specific. On a real Lighthouse run against
 * a build of HEAD, exactly one of 41 routes fails `cumulative-layout-shift`:
 * the student dashboard, at 0.0982, and every shift Lighthouse attributes on
 * that page has the same cause — "Web font loaded", naming Newsreader, Caveat
 * and JetBrains Mono landing on the Momentum panel. Nothing else in the product
 * shifts by a measurable amount.
 *
 * That is worth being exact about, because an earlier reading of a *stale*
 * report (2026-08-12, still naming `instrument-serif`, a face Phase 2 removed)
 * showed 0.2427 and 0.1807 on two teacher routes and made this look like a
 * product-wide failure. It is not, and it has not been since Phase 2 changed
 * the display face. The gate below therefore guards a real 0.098 on the
 * product's most-visited screen, not a crisis.
 *
 * ── Why the plugin throws instead of skipping ──────────────────────────────
 *
 * The failure mode is silent. Rename a font package, change a subset, drop a
 * family, and the matcher stops matching: no preload is emitted, the build
 * succeeds, the page renders, and the shift comes back with nothing on screen
 * or in CI to say so. That is the shape this build keeps being caught by —
 * `--font-serif` (D4.1), `text-display` (D4.4), `lm-head` (D4.5), the banned
 * easing (D4.6), `var()` in a Nivo colour (D5.1) — a thing that resolves to
 * nothing while looking correct. So a missing face fails the build.
 *
 * Caveat's absence from `CRITICAL_FACES` is a decision, not an oversight, and
 * it is asserted below so it stays one.
 */

/** The asset names a real build of this repo emits, hashes and all. */
const REAL_BUNDLE = [
  "index.html",
  "assets/index-Il2c7Bbq.js",
  "assets/index-DQPG77e_.css",
  "assets/schibsted-grotesk-latin-wght-normal-BgDaEnEv.woff2",
  "assets/schibsted-grotesk-latin-ext-wght-normal-DC-KSUi6.woff2",
  "assets/schibsted-grotesk-cyrillic-wght-normal-BEAKL7Jp.woff2",
  "assets/bricolage-grotesque-latin-wght-normal-CCVVNp6i.woff2",
  "assets/bricolage-grotesque-latin-ext-wght-normal-C-3rgBeH.woff2",
  "assets/bricolage-grotesque-vietnamese-wght-normal-Czsa-EzN.woff2",
  "assets/jetbrains-mono-latin-wght-normal-B9CIFXIH.woff2",
  "assets/jetbrains-mono-latin-ext-wght-normal-DBQx-q_a.woff2",
]

describe("the critical set", () => {
  it("is the three faces that render on first paint, in reading order", () => {
    expect(CRITICAL_FACES.map((f) => f.pattern.source)).toEqual([
      "^schibsted-grotesk-latin-wght-normal-[\\w-]+\\.woff2$",
      "^bricolage-grotesque-latin-wght-normal-[\\w-]+\\.woff2$",
      "^jetbrains-mono-latin-wght-normal-[\\w-]+\\.woff2$",
    ])
  })

  it("names no retired Study Notebook face", () => {
    // Geist, Newsreader and Caveat left the bundle with the v5 Abyss type system.
    const sources = CRITICAL_FACES.map((f) => f.pattern.source).join(" ")
    for (const retired of ["caveat", "newsreader", "geist"]) expect(sources).not.toContain(retired)
  })

  it("names only latin, only normal, only variable-weight files", () => {
    for (const face of CRITICAL_FACES) {
      expect(face.pattern.source).toContain("-latin-")
      expect(face.pattern.source).toContain("wght-normal")
      // `-latin-ext-` / `-cyrillic-` / `-italic` each carry their own
      // unicode-range or style and are never needed for English body text.
      expect(face.pattern.source).not.toContain("italic")
    }
  })
})

describe("selectCriticalFontAssets", () => {
  it("picks exactly the three critical faces out of a real bundle", () => {
    expect(selectCriticalFontAssets(REAL_BUNDLE)).toEqual([
      "assets/schibsted-grotesk-latin-wght-normal-BgDaEnEv.woff2",
      "assets/bricolage-grotesque-latin-wght-normal-CCVVNp6i.woff2",
      "assets/jetbrains-mono-latin-wght-normal-B9CIFXIH.woff2",
    ])
  })

  it("does not pick the latin-ext, cyrillic or vietnamese subsets", () => {
    const picked = selectCriticalFontAssets(REAL_BUNDLE).join(" ")
    expect(picked).not.toContain("latin-ext")
    expect(picked).not.toContain("cyrillic")
    expect(picked).not.toContain("vietnamese")
  })

  it("throws, naming the face and its role, when one goes missing", () => {
    // Verified by inversion: this is the exact scenario the plugin exists to
    // make loud — a font package renamed or dropped, everything else fine.
    const withoutDisplay = REAL_BUNDLE.filter((f) => !f.includes("bricolage-grotesque-latin-wght"))
    expect(() => selectCriticalFontAssets(withoutDisplay)).toThrow(
      /bricolage.*every page title and section heading/s,
    )
  })

  it("throws when a pattern stops identifying a single file", () => {
    // Two matches means the subset naming changed under us. Preloading both
    // would hide that, so it is reported the same way a miss is.
    const ambiguous = [...REAL_BUNDLE, "assets/schibsted-grotesk-latin-wght-normal-ZZZZZZZZ.woff2"]
    expect(() => selectCriticalFontAssets(ambiguous)).toThrow(/matched 2 assets/)
  })

  it("throws on an empty bundle rather than emitting no preloads", () => {
    expect(() => selectCriticalFontAssets([])).toThrow(/critical faces/)
  })
})

describe("preloadTagFor", () => {
  it("carries crossorigin", () => {
    /*
     * Not optional and not cargo-cult, even though the fonts are same-origin.
     * CSS always fetches fonts in CORS mode, so a preload without `crossorigin`
     * is a different cache key: the face is downloaded twice and the preload
     * warns "preloaded but not used" while fixing nothing. This assertion is
     * the whole reason this function is separate from the plugin.
     */
    expect(preloadTagFor("assets/geist-latin-wght-normal-A.woff2", "/")).toContain("crossorigin")
  })

  it("declares as=font and the woff2 type", () => {
    const tag = preloadTagFor("assets/geist-latin-wght-normal-A.woff2", "/")
    expect(tag).toContain('rel="preload"')
    expect(tag).toContain('as="font"')
    expect(tag).toContain('type="font/woff2"')
  })

  it("joins base and filename without doubling the slash", () => {
    expect(preloadTagFor("assets/a.woff2", "/")).toContain('href="/assets/a.woff2"')
    expect(preloadTagFor("/assets/a.woff2", "/")).toContain('href="/assets/a.woff2"')
    expect(preloadTagFor("assets/a.woff2", "/app/")).toContain('href="/app/assets/a.woff2"')
  })
})

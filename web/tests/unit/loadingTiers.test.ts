import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * DESIGN.md §12's loading tiers, pinned across the places they have to agree
 * (PR 2 part B).
 *
 * Four checks, one per surface that can silently drift from the others:
 *
 *   - `index.css` declares the two tokens at the approved values — the single
 *     source `RouteFallback` and the pre-mount shell (`preMountShell.ts`) both
 *     read from.
 *   - every `RouteFallback` call site in `routes.tsx` (the top-level routes)
 *     carries `frame="standalone"` — a call site that regresses to the
 *     bare default would silently render the portal-shaped content skeleton
 *     for a sign-in form, which is exactly the promise-of-chrome-that-never-
 *     arrives DESIGN.md's brief warns against.
 *   - `DESIGN.md` §9.2 states the mark's self-drawing stroke as the one
 *     documented exception to "animate only transform and opacity" — the rest
 *     of this system's gates (`motionDefaults.test.ts`, `a11yRules.test.ts`)
 *     enforce that rule; this is what keeps them from having to special-case
 *     `stroke-dashoffset` without a documented reason to point at.
 *   - `lm-appear` and its two tier classes stage on `visibility`, not just
 *     `opacity` (adversarial-review BLOCKER 1) — `opacity: 0` alone leaves an
 *     element in the accessibility tree and the tab order, and both tiers sit
 *     inside `RouteFallback`'s `role="status"` region.
 */

const ROOT = join(import.meta.dirname, "..", "..")

describe("index.css declares the loading-tier tokens", () => {
  const css = readFileSync(join(ROOT, "src/index.css"), "utf8")

  it("declares --loading-tier-skeleton at 200ms", () => {
    expect(css).toMatch(/--loading-tier-skeleton:\s*200ms\s*;/)
  })

  it("declares --loading-tier-slow at 5000ms", () => {
    expect(css).toMatch(/--loading-tier-slow:\s*5000ms\s*;/)
  })

  it("names DESIGN.md §12 near the tokens", () => {
    const start = css.indexOf("--loading-tier-skeleton")
    const context = css.slice(Math.max(0, start - 800), start)
    expect(context).toContain("§12")
  })
})

describe("routes.tsx: every top-level RouteFallback is frame=\"standalone\"", () => {
  const routes = readFileSync(join(ROOT, "src/routes.tsx"), "utf8")

  it("has at least one RouteFallback call site", () => {
    const calls = routes.match(/<RouteFallback\b[^/]*\/>/g) ?? []
    expect(calls.length).toBeGreaterThan(0)
  })

  it("has no RouteFallback call site missing frame=\"standalone\"", () => {
    const calls = routes.match(/<RouteFallback\b[^/]*\/>/g) ?? []
    const missing = calls.filter((call) => !call.includes('frame="standalone"'))
    expect(missing).toEqual([])
  })
})

/*
 * Adversarial-review BLOCKER 1, pinned here too (see preMountShell.test.ts's
 * fuller version for the shell markup): `opacity: 0` alone does not remove an
 * element from the accessibility tree or the tab order, and `.lm-tier-slow`
 * sits inside `RouteFallback`'s `role="status"` region, so tier 3's "Still
 * loading… Reload the page" was announced and Tab-reachable on every route
 * transition, for the first 5s, without ever being visible on screen.
 */
describe("index.css: lm-appear keyframe and tier classes are visibility:hidden until their delay", () => {
  const css = readFileSync(join(ROOT, "src/index.css"), "utf8")

  it("lm-appear starts visibility:hidden and ends visibility:visible", () => {
    const start = css.indexOf("@keyframes lm-appear")
    expect(start).toBeGreaterThan(-1)
    const end = css.indexOf("}", css.indexOf("}", start) + 1)
    const block = css.slice(start, end + 1)
    expect(block).toMatch(/from\s*\{[^}]*visibility:\s*hidden/)
    expect(block).toMatch(/to\s*\{[^}]*visibility:\s*visible/)
  })

  it(".lm-tier-skeleton and .lm-tier-slow both set visibility:hidden as their pre-animation state", () => {
    for (const cls of [".lm-tier-skeleton", ".lm-tier-slow"]) {
      const start = css.indexOf(`${cls} {`)
      expect(start, `${cls} rule not found`).toBeGreaterThan(-1)
      const end = css.indexOf("}", start)
      const rule = css.slice(start, end)
      expect(rule).toMatch(/visibility:\s*hidden/)
      expect(rule).toMatch(/animation:\s*lm-appear/)
    }
  })
})

describe("DESIGN.md §9.2 documents the self-drawing-stroke exception", () => {
  const designDoc = readFileSync(join(ROOT, "..", "DESIGN.md"), "utf8")

  it("contains the exception sentence", () => {
    const section92Start = designDoc.indexOf("### 9.2 Rules")
    const section93Start = designDoc.indexOf("### 9.3", section92Start)
    const section92 = designDoc.slice(section92Start, section93Start)
    expect(section92).toContain("stroke-dashoffset")
    expect(section92).toMatch(/one (permitted|documented) (non-transform\/opacity )?(exception|animation)/)
  })

  it("names the slow-load tier as the reason for the exception", () => {
    const section92Start = designDoc.indexOf("### 9.2 Rules")
    const section93Start = designDoc.indexOf("### 9.3", section92Start)
    const section92 = designDoc.slice(section92Start, section93Start)
    expect(section92.toLowerCase()).toContain("slow-load")
  })
})

import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * DESIGN.md §12's loading tiers, pinned across the places they have to agree
 * (PR 2 part B; routes.tsx block rewritten for packet B1).
 *
 * Four checks, one per surface that can silently drift from the others:
 *
 *   - `index.css` declares the two tokens at the approved values — the single
 *     source `RouteFallback` and the pre-mount shell (`preMountShell.ts`) both
 *     read from.
 *   - `routes.tsx` no longer has a bare `<RouteFallback` call site at all
 *     (packet B1 replaced every one with `<RouteSkeleton />`, which reads
 *     `frame` off the matched route's own `handle.skeleton` instead of every
 *     call site having to remember to pass `frame="standalone"`) — and
 *     `route-skeleton.tsx`'s own `RouteSkeleton` component is what actually
 *     passes `frame="standalone"` once `skeletonForMatches` resolves to that
 *     shape. `tests/unit/routeSkeleton.test.ts` owns the fuller set of
 *     packet-B1 assertions (the `handle.skeleton` pairing checks, the
 *     `skeletonForMatches` unit tests); this file keeps only the two checks
 *     that were already here.
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

  /*
   * The invariant, not the instance. An earlier version of this test named
   * the two tier classes directly, which catches someone DELETING an
   * exemption but not someone ADDING a third staged element and forgetting
   * one — the same shape of gap as this file's token assertions, which
   * stayed green while the interaction they describe was broken (2156e8f2,
   * caught in review).
   *
   * The invariant is decidable from the text because there is a clean
   * marker: a zero-duration animation is STAGING, not motion. Nothing moves,
   * so the delay is the gate rather than a stagger — which is exactly what
   * separates the tiers from the 16 real staggered delays elsewhere, with no
   * judgement needed about whether a `var()` resolves to a time.
   *
   * The `toEqual` line is the sanity clause. If a refactor expresses these
   * another way, the sweep finds nothing and this fails loudly, rather than
   * matching an empty set and passing — which is how the original defect got
   * through in the first place.
   *
   * Known gap, accepted: this does not catch `visibility: visible !important`
   * being added to the blanket rule, or `lm-appear` losing its explicit
   * `from`. Those are not realistic edits; "add a fourth loading tier" is.
   * The behavioural counterpart lives in `e2e/reduced-motion.spec.ts`.
   */
  it("exempts every zero-duration animation from the reduced-motion delay reset", () => {
    const staged = [...css.matchAll(/(\.[\w-]+)\s*\{[^}]*animation:\s*[\w-]+\s+0s\b/g)].map(
      (m) => m[1],
    )
    expect(staged).toEqual([".lm-tier-skeleton", ".lm-tier-slow"])

    const reducedMotion = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"))
    expect(reducedMotion).toMatch(/animation-delay:\s*0\.001ms\s*!important/)
    for (const selector of staged) {
      expect(
        reducedMotion,
        `${selector} stages on its delay, so it must be carved out of the reset`,
      ).toMatch(new RegExp(`\\${selector}\\s*\\{[^}]*animation-delay:[^;]+!important`))
    }
  })

  it("names DESIGN.md §12 near the tokens", () => {
    const start = css.indexOf("--loading-tier-skeleton")
    const context = css.slice(Math.max(0, start - 800), start)
    expect(context).toContain("§12")
  })
})

describe("routes.tsx: zero <RouteFallback call sites (packet B1)", () => {
  const routes = readFileSync(join(ROOT, "src/routes.tsx"), "utf8")

  it("has no <RouteFallback call site", () => {
    expect(routes).not.toMatch(/<RouteFallback\b/)
  })
})

describe('route-skeleton.tsx: RouteSkeleton passes frame="standalone" for the standalone shape', () => {
  const source = readFileSync(join(ROOT, "src/components/ui/route-skeleton.tsx"), "utf8")

  it('renders frame={shape === "standalone" ? "standalone" : "content"}', () => {
    expect(source).toMatch(/frame=\{shape === "standalone" \? "standalone" : "content"\}/)
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

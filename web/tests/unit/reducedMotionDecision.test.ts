import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { prefersReducedMotion } from "@/lib/celebration"

/*
 * C4 (Task 11): `prefersReducedMotion` becomes unit-testable by accepting an
 * injected `matchMedia`-shaped function, instead of always reaching for
 * `window.matchMedia` — this runner has no jsdom/window at all
 * (`vitest.config.ts`, D3.20), so without the injection point this decision
 * could only ever be covered by the Playwright suite.
 *
 * The default parameter keeps every production call site (`useCountUp`,
 * `Flourish` in `components/ui/celebration.tsx`) unchanged: both still call
 * `prefersReducedMotion()` with no argument.
 */
describe("prefersReducedMotion", () => {
  it("returns true when the injected query matches", () => {
    expect(prefersReducedMotion(() => ({ matches: true }))).toBe(true)
  })

  it("returns false when the injected query does not match", () => {
    expect(prefersReducedMotion(() => ({ matches: false }))).toBe(false)
  })

  /*
   * The safe default for a motion decision is not to move. This mirrors the
   * function's own doc comment: "Returns true when matchMedia is
   * unavailable" — the zero-arg form on a runner with no window resolves the
   * default parameter to undefined, not to a throwing window.matchMedia
   * lookup.
   */
  it("defaults to true (no motion) when no matchMedia is available", () => {
    expect(prefersReducedMotion(undefined)).toBe(true)
  })
})

describe("production call sites stay on the zero-arg form", () => {
  const ROOT = join(import.meta.dirname, "..", "..")
  const src = readFileSync(join(ROOT, "src/components/ui/celebration.tsx"), "utf8")

  it("useCountUp calls prefersReducedMotion()", () => {
    expect(src).toMatch(/prefersReducedMotion\(\)/)
  })

  it("Flourish calls prefersReducedMotion()", () => {
    const flourishStart = src.indexOf("function Flourish")
    expect(flourishStart).toBeGreaterThan(-1)
    const afterFlourish = src.slice(flourishStart)
    expect(afterFlourish).toMatch(/prefersReducedMotion\(\)/)
  })
})

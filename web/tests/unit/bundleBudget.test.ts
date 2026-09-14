import { describe, expect, it } from "vitest"
import {
  budgetFor,
  overBudget,
  // @ts-expect-error — plain .mjs gate script, no type declarations by design.
} from "../../scripts/check-bundle-budget.mjs"

/*
 * Packet A8 — pins `scripts/check-bundle-budget.mjs`'s pure `overBudget`
 * function against fixture entries. The script's own CLI wrapper gzips the
 * real `dist/assets/*.js` files and calls this same function; `postbuild`
 * (`npm run build` → `npm run check:bundle`) is what actually enforces it.
 *
 * Task 11 (B6c) adds `budgetFor`/`KNOWN_HEAVY_LAZY_CHUNKS` — a narrow,
 * named exemption for the lazy `assemblePages-*.js` chunk (`pdf-lib`, no
 * tree-shakeable core, ~171KB gzipped even after being split out of
 * `CorrectPaper`) at its own 175KB ceiling, while every other chunk still
 * uses the general 150KB default. The exemption tests below pass an
 * explicit `knownHeavy` fixture rather than relying on the script's live
 * default, so they keep pinning the *mechanism* even if the real default's
 * prefix/ceiling changes later.
 */

describe("overBudget", () => {
  it("returns an empty array when every chunk is under budget", () => {
    const entries = [
      { file: "index-abc123.js", gzipKb: 130.5 },
      { file: "CorrectPaper-def456.js", gzipKb: 184.28 },
    ]
    expect(overBudget(entries, 200)).toEqual([])
  })

  it("names every chunk strictly over budget", () => {
    const entries = [
      { file: "index-abc123.js", gzipKb: 130.5 },
      { file: "chart-data-table-xyz.js", gzipKb: 220.1 },
    ]
    expect(overBudget(entries, 200)).toEqual(["chart-data-table-xyz.js"])
  })

  it("treats a chunk exactly at budget as not over", () => {
    const entries = [{ file: "exact.js", gzipKb: 200 }]
    expect(overBudget(entries, 200)).toEqual([])
  })

  it("respects a lower budget (e.g. Phase B's 150KB)", () => {
    const entries = [{ file: "index-abc123.js", gzipKb: 180 }]
    expect(overBudget(entries, 150)).toEqual(["index-abc123.js"])
  })

  it("returns every offender, not just the first", () => {
    const entries = [
      { file: "a.js", gzipKb: 250 },
      { file: "b.js", gzipKb: 100 },
      { file: "c.js", gzipKb: 300 },
    ]
    expect(overBudget(entries, 200)).toEqual(["a.js", "c.js"])
  })

  it("handles an empty entry list", () => {
    expect(overBudget([], 200)).toEqual([])
  })
})

describe("budgetFor (KNOWN_HEAVY_LAZY_CHUNKS exemption)", () => {
  const knownHeavy = [{ prefix: "assemblePages-", budgetKb: 175, reason: "pdf-lib, lazy" }]

  it("returns the default budget for a chunk matching no exemption", () => {
    expect(budgetFor("index-abc123.js", 150, knownHeavy)).toBe(150)
  })

  it("returns an exemption's own ceiling for a chunk matching its prefix", () => {
    expect(budgetFor("assemblePages-ZsMA4osb.js", 150, knownHeavy)).toBe(175)
  })

  it("matches by prefix, not exact or substring-anywhere", () => {
    expect(budgetFor("lib-assemblePages-x.js", 150, knownHeavy)).toBe(150)
  })

  it("with no exemptions configured, every chunk uses the default", () => {
    expect(budgetFor("assemblePages-ZsMA4osb.js", 150, [])).toBe(150)
  })
})

describe("overBudget with KNOWN_HEAVY_LAZY_CHUNKS exemptions", () => {
  const knownHeavy = [{ prefix: "assemblePages-", budgetKb: 175, reason: "pdf-lib, lazy" }]

  it("an exempt chunk under its own ceiling is not an offender, even over the general budget", () => {
    const entries = [{ file: "assemblePages-ZsMA4osb.js", gzipKb: 170.97 }]
    expect(overBudget(entries, 150, knownHeavy)).toEqual([])
  })

  it("an exempt chunk over its own ceiling is still an offender", () => {
    const entries = [{ file: "assemblePages-ZsMA4osb.js", gzipKb: 180 }]
    expect(overBudget(entries, 150, knownHeavy)).toEqual(["assemblePages-ZsMA4osb.js"])
  })

  it("a non-exempt chunk over the general budget is still an offender even when exemptions exist", () => {
    const entries = [
      { file: "assemblePages-ZsMA4osb.js", gzipKb: 170.97 },
      { file: "CorrectPaper-abc.js", gzipKb: 160 },
    ]
    expect(overBudget(entries, 150, knownHeavy)).toEqual(["CorrectPaper-abc.js"])
  })

  it("uses the real default KNOWN_HEAVY_LAZY_CHUNKS when knownHeavy is omitted", () => {
    // The script's own live exemption list, not the fixture above — this is
    // the one test that would need updating if the real default's prefix or
    // ceiling ever changes, which is the point: it pins the actual guard.
    const entries = [{ file: "assemblePages-ZsMA4osb.js", gzipKb: 170.97 }]
    expect(overBudget(entries, 150)).toEqual([])
  })
})

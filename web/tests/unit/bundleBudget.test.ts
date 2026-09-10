import { describe, expect, it } from "vitest"
import {
  overBudget,
  // @ts-expect-error — plain .mjs gate script, no type declarations by design.
} from "../../scripts/check-bundle-budget.mjs"

/*
 * Packet A8 — pins `scripts/check-bundle-budget.mjs`'s pure `overBudget`
 * function against fixture entries. The script's own CLI wrapper gzips the
 * real `dist/assets/*.js` files and calls this same function; `postbuild`
 * (`npm run build` → `npm run check:bundle`) is what actually enforces it.
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

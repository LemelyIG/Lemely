import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * C3a (Task 6) · the red-pen register: the per-question wrong-answer
 * explanation reads in `--mark-wrong` ink with a left rule, never a fill.
 * Source-text pins (D3.20 — no jsdom, so component *rendering* is not
 * exercised here; Playwright covers the rendered result).
 */

const ROOT = join(process.cwd())

function sourceOf(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("index.css .lm-red-pen", () => {
  const css = sourceOf("src/index.css")

  it("is declared", () => {
    expect(css).toContain(".lm-red-pen")
  })

  it("declares no background property — ink and a rule only", () => {
    const match = css.match(/\.lm-red-pen\s*\{([^}]*)\}/)
    expect(match).not.toBeNull()
    expect(match![1]).not.toMatch(/background/)
  })

  it("colors the ink with --mark-wrong and adds a left rule", () => {
    const match = css.match(/\.lm-red-pen\s*\{([^}]*)\}/)
    expect(match![1]).toContain("var(--mark-wrong)")
    expect(match![1]).toContain("border-inline-start")
  })
})

describe("question-row.tsx", () => {
  const source = sourceOf("src/components/ui/question-row.tsx")

  it("accepts a register prop", () => {
    expect(source).toContain('register?: "plain" | "red-pen"')
  })

  it("applies lm-red-pen only inside the expanded slot, not the whole row", () => {
    // The expanded slot is the wrapper around `children` (`open && children`);
    // the top-level row wrapper (the element carrying the print class) must
    // not also carry the register class.
    const rowWrapperMatch = source.match(/lm-print-avoid-break[\s\S]{0,120}/)
    expect(rowWrapperMatch).not.toBeNull()
    expect(rowWrapperMatch![0]).not.toContain("lm-red-pen")

    const expandedSlotMatch = source.match(/open && children[\s\S]{0,200}/)
    expect(expandedSlotMatch).not.toBeNull()
    expect(expandedSlotMatch![0]).toContain("lm-red-pen")
  })
})

describe("PaperResult.tsx", () => {
  const source = sourceOf("src/portals/student/screens/PaperResult.tsx")

  it("passes register= to QuestionRow, derived from markState", () => {
    expect(source).toMatch(/register=\{markState\(q\) === "wrong" \? "red-pen" : "plain"\}/)
  })

  it("keeps the feedback panel on bg-paper-sunk (the register never touches it)", () => {
    expect(source).toContain("bg-paper-sunk")
  })
})

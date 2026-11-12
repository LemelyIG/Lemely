import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"
import { ringDash } from "@/components/ui/progress-ring"

/*
 * C1b (Task 2). `ringDash` is `Grading.tsx`'s inline
 * `${(CIRC * progress).toFixed(1)} ${CIRC.toFixed(1)}` extracted verbatim as
 * a pure function so the dash-array math is testable without a DOM (D3.20 —
 * this suite runs under Node, no jsdom). `ProgressRing` composes it into the
 * reusable primitive; no other file should hand-roll this arithmetic again.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

function sourceOf(relative: string): string {
  return stripComments(fs.readFileSync(path.join(ROOT, relative), "utf8"))
}

describe("ringDash", () => {
  it("computes the filled/total dash-array pair for a mid-range value", () => {
    expect(ringDash(50, 100)).toBe("50.0 100.0")
  })

  it("clamps a value above 100 to a full ring", () => {
    expect(ringDash(150, 100)).toBe("100.0 100.0")
  })

  it("clamps a negative value to an empty ring", () => {
    expect(ringDash(-5, 100)).toBe("0.0 100.0")
  })
})

describe("progress-ring.tsx (source)", () => {
  const source = sourceOf("src/components/ui/progress-ring.tsx")

  it("never animates the dash array — DESIGN.md §9.2 permits transform/opacity only, and a ring changes value discretely", () => {
    expect(source).not.toMatch(/transition/i)
  })
})

describe("Grading.tsx renders its grading ring through ProgressRing (source)", () => {
  const source = sourceOf("src/portals/teacher/screens/Grading.tsx")

  it("uses the shared primitive", () => {
    expect(source).toContain("<ProgressRing")
  })

  it("no longer hand-rolls the dasharray", () => {
    expect(source).not.toContain("strokeDasharray")
  })

  it("the CIRC/dash locals are gone", () => {
    expect(source).not.toContain("CIRC")
  })
})

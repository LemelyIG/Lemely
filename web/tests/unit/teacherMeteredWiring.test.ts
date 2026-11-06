import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

const ROOT = join(import.meta.dirname, "..", "..")
const read = (p: string) => stripComments(readFileSync(join(ROOT, p), "utf8"))

describe("Grading.tsx", () => {
  const source = read("src/portals/teacher/screens/Grading.tsx")

  it("gates the upload on a mark_paper estimate with the page count", () => {
    expect(source).toContain('action: "mark_paper"')
    expect(source).toMatch(/<EstimateRange[\s\S]*?gate=\{uploadGate\}[\s\S]*?audience="teacher"[\s\S]*?subjectUnknown/)
    expect(source).toContain("if (uploadGate.captureError(err))")
  })

  it("gates the regrade on a regrade estimate for the selected paper", () => {
    expect(source).toContain('action: "regrade"')
    expect(source).toMatch(/<EstimateRange[\s\S]*?gate=\{regradeGate\}/)
    expect(source).toContain("disabled={regrade.isPending || regradeGate.block !== null}")
    expect(source).toContain("!parseUsageBlock(regrade.error)")
  })

  it("refreshes the meter after both", () => {
    expect(source.match(/invalidateUsage\(/g)?.length ?? 0).toBeGreaterThanOrEqual(2)
  })
})

describe("QuizBuilder.tsx", () => {
  const source = read("src/portals/teacher/screens/QuizBuilder.tsx")

  it("gates generation on a generate_quiz estimate", () => {
    expect(source).toContain('action: "generate_quiz"')
    expect(source).toMatch(/<EstimateRange[\s\S]*?gate=\{generateGate\}[\s\S]*?audience="teacher"/)
    expect(source).toContain("disabled={!canGenerate || generate.isPending || generateGate.block !== null}")
    expect(source).toContain("generateGate.captureError(")
    expect(source).toContain("!parseUsageBlock(generate.error)")
    expect(source).toContain("invalidateUsage(")
  })
})

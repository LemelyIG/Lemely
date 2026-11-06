import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { generateQuizEstimateRequest } from "@/lib/quizEstimateRequest"
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
    expect(source).toContain("generateQuizEstimateRequest(")
    expect(source).toMatch(/<EstimateRange[\s\S]*?gate=\{generateGate\}[\s\S]*?audience="teacher"/)
    expect(source).toContain("disabled={!canGenerate || generate.isPending || generateGate.block !== null}")
    expect(source).toContain("generateGate.captureError(")
    expect(source).toContain("!parseUsageBlock(generate.error)")
    expect(source).toContain("invalidateUsage(")
  })

  it("shows the blocked notice itself when no estimate request exists to carry a 402", () => {
    expect(source).toContain("generateGate.request === null && generate.isError ? parseUsageBlock(generate.error) : null")
    expect(source).toMatch(/\{unpricedBlock \? \([\s\S]*?<UsageBlockedNotice[\s\S]*?block=\{unpricedBlock\}[\s\S]*?audience="teacher"/)
  })
})

describe("generateQuizEstimateRequest", () => {
  const base = { enabled: true, requestedCount: 12, includedCount: 4 }

  it("prices the questions still missing, capped at 50", () => {
    expect(generateQuizEstimateRequest(base)).toEqual({ action: "generate_quiz", count: 8 })
    expect(generateQuizEstimateRequest({ ...base, requestedCount: 200, includedCount: 0 })).toEqual({ action: "generate_quiz", count: 50 })
  })

  it("prices the default job when no count was requested", () => {
    expect(generateQuizEstimateRequest({ ...base, requestedCount: null })).toEqual({ action: "generate_quiz" })
  })

  it("builds no request when nothing is missing or generation is unavailable", () => {
    expect(generateQuizEstimateRequest({ ...base, includedCount: 12 })).toBeNull()
    expect(generateQuizEstimateRequest({ ...base, includedCount: 15 })).toBeNull()
    expect(generateQuizEstimateRequest({ ...base, enabled: false })).toBeNull()
  })
})

describe("Grading.tsx accessibility and copy", () => {
  const source = read("src/portals/teacher/screens/Grading.tsx")

  it("fits both estimate notices under the h1 with level-2 headings", () => {
    expect(source.match(/headingLevel=\{2\}/g)?.length ?? 0).toBe(2)
  })

  it("does not call a blocked regrade a pause", () => {
    expect(source).toContain("Regrade unavailable")
    expect(source).not.toContain("Marking paused")
  })
})

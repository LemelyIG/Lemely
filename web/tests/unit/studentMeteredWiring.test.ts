import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

const ROOT = join(import.meta.dirname, "..", "..")
const read = (p: string) => stripComments(readFileSync(join(ROOT, p), "utf8"))

const SCREENS = [
  { file: "src/portals/student/screens/CorrectPaper.tsx", action: "mark_paper" },
  { file: "src/portals/student/components/SelfReviewPanel.tsx", action: "self_review" },
  { file: "src/portals/student/screens/studyplan/StudyPlanWeek.tsx", action: "study_plan" },
] as const

describe.each(SCREENS)("$file", ({ file, action }) => {
  const source = read(file)

  it("opens a metered gate for its action", () => {
    expect(source).toContain("useMeteredGate(")
    expect(source).toContain(`action: "${action}"`)
  })

  it("renders the estimate with the student audience", () => {
    expect(source).toMatch(/<EstimateRange[\s\S]*?audience="student"/)
  })

  it("captures a 402 into the gate", () => {
    expect(source).toContain(".captureError(")
  })

  it("refreshes the meter after the action", () => {
    expect(source).toContain("invalidateUsage(")
  })
})

describe("start controls are disabled while blocked", () => {
  it("CorrectPaper disables both start buttons", () => {
    const source = read("src/portals/student/screens/CorrectPaper.tsx")
    expect(source.match(/disabled=\{!canStart \|\| markGate\.block !== null\}/g)?.length).toBe(2)
    expect(source).toContain("subjectUnknown")
  })

  it("SelfReviewPanel passes the block into PendingForm without a fragment in the not_started branch", () => {
    const source = read("src/portals/student/components/SelfReviewPanel.tsx")
    expect(source).toContain("blocked={reviewGate.block !== null}")
    expect(source).toContain("disabled={!complete || submitting || blocked}")
  })

  it("StudyPlanWeek refuses to start while blocked and hides the generic error for a 402", () => {
    const source = read("src/portals/student/screens/studyplan/StudyPlanWeek.tsx")
    expect(source).toContain("if (planGate.block) return")
    expect(source).toContain("!parseUsageBlock(rebuild.error)")
  })

  it("StudyPlanWeek omits the empty-state rebuild action while blocked and renders the estimate before it", () => {
    const source = read("src/portals/student/screens/studyplan/StudyPlanWeek.tsx")
    // notGenerated: the primary CTA is the rebuild; refused: the secondary action is.
    expect(source).toMatch(/action=\{\s*planGate\.block\s*\?\s*undefined\s*:\s*\{\s*label: rebuild\.isPending \? "Building…"/)
    expect(source).toMatch(/secondaryAction=\{\s*planGate\.block\s*\?\s*undefined\s*:\s*\{\s*label: rebuild\.isPending \? "Rebuilding…"/)
    for (const marginalia of ["A blank week, for now", "Not enough to go on yet"]) {
      const at = source.indexOf(`marginalia="${marginalia}"`)
      expect(at).toBeGreaterThan(0)
      const head = source.slice(0, at)
      expect(head.lastIndexOf("{estimate}")).toBeGreaterThan(head.lastIndexOf("return ("))
    }
  })
})

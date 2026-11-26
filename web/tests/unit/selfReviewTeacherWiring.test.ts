import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { isIntegrityReason, reasonLabel, REASON_LABEL } from "@/portals/teacher/screens/review/reviewLabels"
import { stripComments } from "./support/jsxSource"

/*
 * S2 part2+3 final review, I-2 (teacher-side half, closed by db-side commit
 * 61f07cab; this covers what that commit explicitly left to web/).
 *
 * A `student_evidence_unjudged` queue row is what a challenged mark under
 * `judge=None` becomes — the common path with no Gemini key configured, per
 * the finding, not an edge case. Before this: the row rendered its raw enum
 * string (`reasonLabel` had no entry, so it fell through to `reason` itself),
 * could not be filtered for, and `ReviewItemDetail` carried no point rows at
 * all — a teacher opening the item had nothing to read except "a teacher
 * will look at this" on the student's own screen.
 */

const ROOT = join(import.meta.dirname, "..", "..")

function readSource(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("review labels — student_evidence_unjudged is labelled and filterable", () => {
  it("REASON_LABEL carries a human label, not the raw enum string", () => {
    expect(REASON_LABEL.student_evidence_unjudged).toBe("Student challenged a mark")
    expect(reasonLabel("student_evidence_unjudged")).toBe("Student challenged a mark")
  })

  it("is not treated as an integrity reason (accept/adjust controls, not dismiss-only)", () => {
    // The answer panel renders dismiss-only for an integrity reason and
    // accept/adjust-marks for everything else. A challenged mark is a
    // marking dispute, not an integrity signal — it must take the normal
    // resolve path, the one that can actually move the student's mark.
    expect(isIntegrityReason("student_evidence_unjudged")).toBe(false)
  })

  it("is a selectable filter option, not just a label (final review I-2)", () => {
    // A whole-file `toContain` on the label string alone would already
    // pass from REASON_LABEL above; this must appear specifically inside
    // the filter options array, which is what actually lets a teacher
    // select the reason in the UI.
    const source = readSource("src/portals/teacher/screens/review/reviewLabels.ts")
    const optionsStart = source.indexOf("const REASON_FILTER_OPTIONS")
    expect(optionsStart).toBeGreaterThan(-1)
    const arrayStart = source.indexOf("= [", optionsStart)
    expect(arrayStart).toBeGreaterThan(optionsStart)
    const optionsEnd = source.indexOf("]", arrayStart)
    const optionsBody = source.slice(arrayStart, optionsEnd)
    expect(optionsBody).toContain('{ value: "student_evidence_unjudged", label: "Student challenged a mark" }')
  })
})

describe("answerView.ts — a challenged mark's points are readable, not just named", () => {
  const source = readSource("src/portals/teacher/screens/review/answerView.ts")

  it("builds the self-review block from the detail's own points, not a stand-in", () => {
    expect(source).toContain("d.points")
    expect(source).toContain("selfReview:")
  })

  it("shows the student's claim, the marker's verdict, and the evidence text", () => {
    // The marker's own verdict and the student's claim, both: a teacher adjudicating a
    // disagreement needs both sides, not just one.
    expect(source).toContain("p.studentSelfmark")
    // The actual text the student wrote, the sentence the queue row exists to have a human read.
    expect(source).toContain("p.studentEvidence")
    expect(source).toContain("p.evidenceVerdict")
    // An unjudged point (the common `judge=None` case) must say so rather than render nothing.
    expect(source).toContain("Not yet judged")
  })

  it("only includes points the student actually self-marked, not every scheme point on the question", () => {
    expect(source).toContain("p.studentSelfmark !== null")
  })

  it("renders student-authored evidence as plain JSX text, never as markup", () => {
    // No dangerouslySetInnerHTML in the view model or the panel that draws it: a teacher-console
    // exemption from student-facing sanitising is about withholding nothing, not trusting bytes as HTML.
    expect(source).not.toContain("dangerouslySetInnerHTML")
    expect(readSource("src/portals/teacher/screens/review/AnswerPanel.tsx")).not.toContain("dangerouslySetInnerHTML")
  })
})

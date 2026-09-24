import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Task 14 · source-text gates for `SelfReviewPanel`. Not mountable under this
 * suite's DOM-less Node environment (`vitest.config.ts`, D3.20) — same
 * reasoning as `selfReviewWiring.test.ts` and `capabilityWiring.test.ts` — so
 * the reveal-safety contract and the three fixed test ids (Task 15 and the
 * Playwright task depend on them) are pinned as text instead.
 *
 * What these gates exist to catch: a panel that reads `view.awarded` or any
 * other verdict field before the server has actually revealed one. The
 * pending shape (`SelfReviewPending`, `selfReviewTypes.ts`) carries no
 * `awarded` field at all, so there is nothing to leak *if* the pending branch
 * only ever renders `PendingForm` — a future edit that pulled a verdict field
 * into the pending branch, or dropped the `not_started` gate entirely, would
 * pass typecheck (the type only forbids it on `SelfReviewPending` itself) and
 * ship a real leak. This gate would catch it.
 */

const ROOT = join(import.meta.dirname, "..", "..")

function readSource(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("SelfReviewPanel.tsx", () => {
  const source = readSource("src/portals/student/components/SelfReviewPanel.tsx")

  it("carries the three fixed test ids Task 15 and Playwright depend on", () => {
    expect(source).toContain('data-testid="self-review-form"')
    expect(source).toContain('data-testid="self-review-outcome"')
    expect(source).toContain('data-testid="self-review-unavailable"')
  })

  it("renders only PendingForm in the not_started branch, never both branches (Task 13/14 review, IMP-2)", () => {
    // A substring check on 'view.state === "not_started"' cannot tell a
    // clean gate from a `<><RevealedOutcome/><PendingForm .../></>` fragment
    // that leaves the guard string untouched — proven green by the review's
    // E2 evasion. This asserts over the branch's own body instead: it must
    // render PendingForm and must not also render RevealedOutcome or open a
    // fragment that could smuggle a sibling in.
    const guardStart = source.indexOf('if (view.state === "not_started") {')
    expect(guardStart).toBeGreaterThan(-1)
    // The branch ends where the component's final `return <RevealedOutcome`
    // begins — everything up to there is the `not_started` block itself.
    const revealedReturn = source.indexOf("return <RevealedOutcome", guardStart)
    expect(revealedReturn).toBeGreaterThan(guardStart)
    const branch = source.slice(guardStart, revealedReturn)
    expect(branch).toContain("<PendingForm")
    expect(branch).not.toContain("<RevealedOutcome")
    expect(branch).not.toContain("<>")
  })

  it("no verdict field is read anywhere above RevealedOutcome (Task 13/14 re-review, R-4; subsumes IMP-3/E1/M11)", () => {
    // The two gates this replaces sliced [SelfReviewPanel, PendingForm) and
    // [PendingForm, RevealedOutcome) — leaving everything ABOVE
    // `export function SelfReviewPanel` covered by nothing. That region is
    // not hypothetical: this file holds `verdictValue`, `readSavedDraft` and
    // `saveDraft` there. Proven green as evasion E9: a module-level
    // `peekVerdict(view)` helper reading `.points?.[0]?.awarded`, inserted
    // above the component, passed both of the old gates because neither's
    // slice reached it. `RevealedOutcome` is the only legitimate reader of a
    // verdict field and it is the last function in the file, so one gate
    // over everything before it subsumes both old gates and closes E9, E1
    // and M11 together.
    const revealedStart = source.indexOf("function RevealedOutcome")
    expect(revealedStart).toBeGreaterThan(-1)
    // The gate's whole value rests on "RevealedOutcome is last" — an
    // assumption, not a fact the slice itself checks. Proven green as
    // evasion E10 (second re-review): a `peekBelow` helper appended to the
    // END of the file, reading a verdict field, passed clean because the
    // slice never reached it. Pin the assumption instead of hoping it holds:
    // no further top-level `function`/`export function` declaration may
    // start after `RevealedOutcome`.
    expect(source.indexOf("\nfunction ", revealedStart + 1)).toBe(-1)
    expect(source.indexOf("\nexport function ", revealedStart + 1)).toBe(-1)
    const aboveRevealed = source.slice(0, revealedStart)
    for (const field of [
      ".awarded",
      "studentSelfmark",
      "evidenceVerdict",
      "aiMarks",
      "effectiveMarks",
      "markChanged",
      "judgeReason",
      // I6/I7 (task #63): the marker's per-point verdict, evidence quote and
      // ECF flag, added to `SelfReviewRevealedPoint` alongside the fields
      // above. `verdict` alone is too generic to ban bare (`setVerdict`,
      // `verdictValue` and `draft.verdicts` are the student's own draft and
      // legitimately live above this line), so it is pinned dotted, the only
      // shape the marker's verdict is ever read in.
      "point.verdict",
      "ecfApplied",
      "evidenceSpan",
    ]) {
      expect(aboveRevealed).not.toContain(field)
    }
    expect(aboveRevealed).not.toContain("as unknown as SelfReviewRevealed")
  })

  it("declares student-facing labels for the three verdicts, deliberately not the teacher's (task #63, spec 2026-09-24)", () => {
    // Anchored on the map's own literal entries, not a loose substring
    // search, so a widened alias or a copy/paste of the teacher's wording
    // cannot slip past this.
    const labelStart = source.indexOf("STUDENT_VERDICT_LABEL")
    expect(labelStart).toBeGreaterThan(-1)
    const labelBraceStart = source.indexOf("{", labelStart)
    const labelBraceEnd = source.indexOf("}", labelBraceStart)
    const labelBlock = source.slice(labelBraceStart, labelBraceEnd + 1)
    expect(labelBlock).toContain('awarded: "Marked correct"')
    expect(labelBlock).toContain('withheld: "Not shown in your answer"')
    expect(labelBlock).toContain('unverifiable: "We could not find this in your working"')
    // Two vocabularies for one concept are intended here (see the task
    // brief), so the teacher screen's institutional-hedging wording must
    // never appear on this student-facing file.
    expect(source).not.toContain("Withheld, judged absent")
    expect(source).not.toContain("Unverifiable, could not confirm")
  })

  it("renders the verdict chip, ECF chip and evidence span only inside RevealedOutcome", () => {
    const outcomeStart = source.indexOf("function RevealedOutcome")
    expect(outcomeStart).toBeGreaterThan(-1)
    const outcomeBody = source.slice(outcomeStart)
    expect(outcomeBody).toContain("point.verdict ?")
    expect(outcomeBody).toContain("STUDENT_VERDICT_LABEL[point.verdict]")
    expect(outcomeBody).toContain("point.ecfApplied ?")
    expect(outcomeBody).toContain("Carried forward, so one earlier slip did not cost you twice")
    expect(outcomeBody).toContain("point.evidenceSpan ?")
    expect(outcomeBody).toContain("{point.evidenceSpan}")
  })

  it("only RevealedOutcome reads the verdict fields, and only from SelfReviewRevealed", () => {
    const outcomeStart = source.indexOf("function RevealedOutcome")
    expect(outcomeStart).toBeGreaterThan(-1)
    const outcomeBody = source.slice(outcomeStart)
    expect(outcomeBody).toContain("point.awarded")
    expect(outcomeBody).toContain("view: SelfReviewRevealed")
  })

  it("never names an integrity flag in copy or code, panel or copy module (QUALITY-BAR.md: teacher-only, Task 13/14 review IMP-4)", () => {
    // Proven green (E6): the panel's own source is almost entirely markup —
    // the actual user-visible strings (`UNAVAILABLE_COPY`, `OUTCOME_LABEL`,
    // `ABSORBED_COPY`, `evidenceHint()`, `summaryLine()`, `outcomeDetail()`)
    // live in `src/lib/selfReview.ts`, which no integrity-flag gate anywhere
    // in the repo read. Scanning only `source` let `UNAVAILABLE_COPY` name
    // "flagged for plagiarism" straight into a student's EmptyState heading
    // while this test stayed green. This concatenates the copy module in so
    // the same gate covers where the copy actually is. The repo-wide,
    // CI-enforced home for this rule is `scripts/check_copy.mjs`
    // (out of scope here — see the review's IMP-4 preferred fix).
    const copySource = readSource("src/lib/selfReview.ts")
    const combined = `${source}\n${copySource}`.toLowerCase()
    expect(combined).not.toContain("plagiar")
    expect(combined).not.toContain("ai_detection")
    expect(combined).not.toContain("ai detection")
    expect(combined).not.toContain("cheat")
  })

  it("carries no em dash and no exclamation mark in UI copy (REDESIGN-MISSION §3.2 item 10)", () => {
    expect(source).not.toContain("—")
    // Excludes JSX expression braces like `{...props}`; this file has none,
    // so a bare scan for "!" in rendered text is safe. The only "!" in this
    // file's logic is `!complete` / `!submitting`, which are code, not copy —
    // assert no "!" appears immediately before a closing JSX tag or quote,
    // the shape a genuine exclamation-mark sentence would take.
    expect(source).not.toMatch(/[a-zA-Z][!][<"']/)
  })

  it("fetches no self-review data before the reveal (no early GET beyond useSelfReview)", () => {
    expect(source).not.toContain("useQuery(")
    expect((source.match(/useSelfReview\(/g) ?? []).length).toBe(1)
  })

  it("blocks submit on missing evidence for a claimed point, not just on isComplete (final review I-3)", () => {
    // `isComplete` only checks that every point HAS a verdict — a student
    // can tick "I earned this" on an evidence-required question, leave the
    // reason blank, and `isComplete` is still true. Server-side that is
    // `PointDecision.NO_CHANGE`: recorded, mark unmoved, and the pass is
    // one-shot, so nothing brings that mark back. `canSubmit` must fold in
    // `missingEvidence`, and the form's own onSubmit guard must gate on it,
    // not on `complete` alone. Anchored on PendingForm's own body.
    const fnStart = source.indexOf("function PendingForm(")
    expect(fnStart).toBeGreaterThan(-1)
    const fnEnd = source.indexOf("function RevealedOutcome", fnStart)
    expect(fnEnd).toBeGreaterThan(fnStart)
    const body = source.slice(fnStart, fnEnd)
    expect(body).toContain("missingEvidence(draft, view.points, view.evidenceRequired)")
    expect(body).toContain("const canSubmit = complete && missing.length === 0")
    expect(body).toMatch(/if \(canSubmit && !submitting\)/)
    // A whole-file `toContain("missing.includes")` would be satisfied by
    // the Textarea's error prop alone even if onSubmit never checked
    // `canSubmit` — assert the guard AND the visible error live in the same
    // slice.
    expect(body).toContain("missing.includes(point.markPointId)")
  })
})

describe("selfReviewTypes.ts — SelfReviewRevealedPoint carries verdict/evidenceSpan/ecfApplied (task #63)", () => {
  const source = readSource("src/lib/selfReviewTypes.ts")

  it("adds the three I6/I7 fields to SelfReviewRevealedPoint, not to the pending shape", () => {
    const revealedStart = source.indexOf("export interface SelfReviewRevealedPoint")
    expect(revealedStart).toBeGreaterThan(-1)
    const revealedEnd = source.indexOf("}", revealedStart)
    const revealedBody = source.slice(revealedStart, revealedEnd)
    expect(revealedBody).toMatch(/verdict:\s*"awarded"\s*\|\s*"withheld"\s*\|\s*"unverifiable"\s*\|\s*null/)
    expect(revealedBody).toContain("evidenceSpan: string")
    expect(revealedBody).toContain("ecfApplied: boolean")

    // The file's own header states the contract this test enforces: a field
    // named `awarded` on the pending shape means the backend contract was
    // broken, not extended. A verdict is strictly more informative than
    // `awarded`, so it is held to the same rule.
    const pendingStart = source.indexOf("export interface SelfReviewPendingPoint")
    expect(pendingStart).toBeGreaterThan(-1)
    const pendingEnd = source.indexOf("}", pendingStart)
    const pendingBody = source.slice(pendingStart, pendingEnd)
    expect(pendingBody).not.toContain("verdict")
    expect(pendingBody).not.toContain("evidenceSpan")
    expect(pendingBody).not.toContain("ecfApplied")
  })
})

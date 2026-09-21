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

  it("SelfReviewPanel's own body never reads a revealed-only field (Task 13/14 review, IMP-3)", () => {
    // `PendingForm`'s body was covered; `SelfReviewPanel` itself — which owns
    // `query.data` and sits above `function PendingForm` — was not, and is
    // the natural place a leak would actually be written. Proven green by
    // the review's E1 evasion: a verdict read inserted into the exported
    // component's own `not_started` branch, via the exact
    // `as unknown as SelfReviewRevealed` cast this gate now forbids.
    const panelStart = source.indexOf("export function SelfReviewPanel")
    const panelEnd = source.indexOf("function PendingForm")
    expect(panelStart).toBeGreaterThan(-1)
    expect(panelEnd).toBeGreaterThan(panelStart)
    const panelBody = source.slice(panelStart, panelEnd)
    for (const field of [
      ".awarded",
      "studentSelfmark",
      "evidenceVerdict",
      "aiMarks",
      "effectiveMarks",
      "markChanged",
    ]) {
      expect(panelBody).not.toContain(field)
    }
    expect(panelBody).not.toContain("as unknown as SelfReviewRevealed")
  })

  it("never reads point.awarded (or any revealed-only field) inside PendingForm", () => {
    const formStart = source.indexOf("function PendingForm")
    const formEnd = source.indexOf("function RevealedOutcome")
    expect(formStart).toBeGreaterThan(-1)
    expect(formEnd).toBeGreaterThan(formStart)
    const pendingFormBody = source.slice(formStart, formEnd)
    expect(pendingFormBody).not.toContain(".awarded")
    expect(pendingFormBody).not.toContain("studentSelfmark")
    expect(pendingFormBody).not.toContain("evidenceVerdict")
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
})

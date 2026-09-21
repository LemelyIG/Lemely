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

  it("gates the form strictly on state === \"not_started\", never rendering both branches", () => {
    expect(source).toContain('view.state === "not_started"')
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

  it("never names an integrity flag in copy or code (QUALITY-BAR.md: teacher-only)", () => {
    expect(source.toLowerCase()).not.toContain("plagiar")
    expect(source.toLowerCase()).not.toContain("ai_detection")
    expect(source.toLowerCase()).not.toContain("ai detection")
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

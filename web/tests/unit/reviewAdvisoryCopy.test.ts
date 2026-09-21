import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import {
  isIntegrityReason,
  reasonLabel,
  REVIEW_ADVISORY_COPY,
} from "@/portals/teacher/screens/Review"
import { stripComments } from "./support/jsxSource"

/*
 * F4 — the AI-generated-answer detector is gone, and the review queue's
 * standing advisory notice (JCQ guidance; Ofqual's 14 Jan 2026 principles
 * and 16 Jul 2026 approach to AI marking tools; Cambridge's digital-mocks
 * human-verification requirement) is what replaces it on this screen.
 *
 * The copy states only what the product actually enforces (adversarial-
 * review addendum): an earlier draft claimed Lemely "marks in parallel"
 * with a teacher and is "never the sole marker" — nothing in the system
 * guarantees either, so on a compliance-facing screen that was itself an
 * indefensible claim, the same failure mode F4 exists to remove. See
 * `REVIEW_ADVISORY_COPY`'s own doc comment in `Review.tsx` for what IS true
 * and enforced instead.
 *
 * Two layers, deliberately not one: the constant-snapshot tests below pin the
 * exact wording, but pin it whether or not anything on screen ever shows it
 * — a reviewer proved this by deleting the `<p>{REVIEW_ADVISORY_COPY}</p>`
 * block from `Review.tsx` and watching the *entire* web unit suite (189
 * files, 3304 tests) stay green. `vitest.config.ts` runs this suite under
 * Node with no jsdom/@testing-library by design (see that file's own
 * header), so a render test isn't an option here — the fix is the same
 * source-text-scan pattern this repo already uses for the same reason
 * (`ciCopyGate.test.ts`, `reviewBadge.test.ts`): read `Review.tsx`'s stripped
 * source and assert the constant is actually interpolated inside a JSX
 * element the component returns, not merely declared and exported.
 */

const SRC = fileURLToPath(new URL("../../src/", import.meta.url))

function read(relPath: string): string {
  return readFileSync(join(SRC, relPath), "utf8")
}

describe("Review queue advisory copy (F4)", () => {
  it("matches the current wording (provisional, pending product sign-off — see the constant's own doc comment)", () => {
    expect(REVIEW_ADVISORY_COPY).toMatchSnapshot()
  })

  it("names the flags as advisory signals, not a verdict", () => {
    expect(REVIEW_ADVISORY_COPY).toMatch(/advisory/i)
    expect(REVIEW_ADVISORY_COPY).toMatch(/not a verdict/i)
  })

  it("does not assert a universal marking-process behaviour the product doesn't enforce", () => {
    // The claim this replaced ("marks in parallel with you" / "never the
    // sole marker") had no code path backing it — nothing requires a
    // teacher to mark alongside Lemely on every paper. Locking the absence
    // of that phrasing so it can't quietly come back.
    expect(REVIEW_ADVISORY_COPY).not.toMatch(/parallel/i)
    expect(REVIEW_ADVISORY_COPY).not.toMatch(/sole marker/i)
  })

  it("states only the correction behaviour the code actually enforces", () => {
    // `QuestionResult.effective_marks` is the single accessor every screen
    // and DTO reads through, and it always prefers a teacher's correction
    // once one exists — this sentence has a real code path behind it.
    expect(REVIEW_ADVISORY_COPY).toMatch(/correction/i)
    expect(REVIEW_ADVISORY_COPY).toMatch(/student's result reflects/i)
  })

  it("is actually rendered inside a JSX element on the review queue screen", () => {
    // Fails the moment the `<p>{REVIEW_ADVISORY_COPY}</p>` (or equivalent)
    // block is removed from Review.tsx, even though the constant itself
    // still exists and every other test above still passes against it —
    // that gap is exactly what let the reviewer's deletion probe go
    // undetected by the rest of this suite.
    const source = stripComments(read("portals/teacher/screens/Review.tsx"))
    expect(source).toMatch(/<[A-Za-z][^>]*>\s*\{REVIEW_ADVISORY_COPY\}\s*<\/[A-Za-z]+>/)
  })
})

describe("removed AI-generated-answer detector (F4)", () => {
  it("ai_detection_flag is no longer a recognised integrity reason", () => {
    expect(isIntegrityReason("ai_detection_flag")).toBe(false)
  })

  it("plagiarism_flag is renamed away from an accusation-shaped label", () => {
    const label = reasonLabel("plagiarism_flag")
    expect(label).toBe("Matches mark-scheme wording")
    expect(label).not.toMatch(/AI/i)
  })

  it("an unrecognised ai_detection_flag reason falls back to the raw value, not a label", () => {
    // REASON_LABEL has no entry for the removed reason, so reasonLabel's own
    // fallback (`REASON_LABEL[reason] ?? reason`) is what a stale historical
    // row (there are none post-migration-0037, but the type is a bare
    // string) would render as, rather than throwing or showing "undefined".
    expect(reasonLabel("ai_detection_flag")).toBe("ai_detection_flag")
  })
})

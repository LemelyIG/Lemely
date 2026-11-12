import { describe, expect, it } from "vitest"

import { isIntegrityReason, reasonLabel } from "@/portals/teacher/screens/Review"

/*
 * F4 — the AI-generated-answer detector is gone.
 *
 * This file previously also pinned `REVIEW_ADVISORY_COPY`, a standing
 * compliance-facing advisory notice on the review queue. That notice and its
 * tests were REMOVED on the product owner's explicit instruction (2026-09-21),
 * after being shown both that the copy was rendered on the teacher review
 * screen and that this file's own header cited JCQ guidance, Ofqual's
 * 14 Jan 2026 principles and 16 Jul 2026 approach to AI marking tools, and
 * Cambridge's digital-mocks human-verification requirement as the reason it
 * existed. The owner's ruling was that those citations are stale and do not
 * bind the product. Recorded here rather than in a commit message alone,
 * because the next person to read an Ofqual requirement and look for the
 * notice should find out here that its absence is a decision and not an
 * oversight.
 *
 * Also settled at the same time, and the reason the earlier "marks in parallel
 * with you, never in place of you" wording is not merely unbacked but false:
 * Lemely DOES mark unattended. No code path requires a teacher to mark
 * alongside it, and none is intended to.
 *
 * The tests below are unrelated to that copy and stand on their own.
 */

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

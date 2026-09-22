import { describe, expect, it } from "vitest"

import { markerSourceLabel } from "@/portals/student/screens/PaperResult"

/*
 * Second independent review of the US-039 blank-exemption fix (fix-us039-2).
 *
 * `QuestionResult.markerSource` is a wire-level token
 * ("deterministic" | "ai" | "missing" | "dropped" | "blank"), not
 * student-facing copy.
 * Before this fix, `markerSourceLabel` only translated `"dropped"`; every
 * other value — including `"missing"` — passed straight through. That was a
 * latent gap even before US-039 (a `--mcq-only` skip already produced
 * `"missing"`), but US-039's blank short-circuit made it visible on a
 * routine path: a genuinely-unattempted question now renders the raw
 * internal token `"missing"` in the marker chip, with no feedback and no
 * review-reason line (the review queue correctly does not flag it — see
 * `lemely/db/review_queue_rules.py` — so nothing else on the page explains
 * the zero either).
 *
 * `markerSourceLabel("missing")` now reads "not marked", same as
 * `"dropped"`. This intentionally does NOT distinguish a genuine blank from
 * a `--mcq-only` skip or a false-blank extraction miss (US-042, an accepted
 * residual) — that copy decision is a product call, not this fix's to make.
 */
describe("markerSourceLabel", () => {
  it("maps a genuine blank's marker_source to student-facing copy, not the raw token", () => {
    expect(markerSourceLabel("missing")).toBe("not marked")
  })

  it("keeps the existing dropped->not marked mapping (US-038)", () => {
    expect(markerSourceLabel("dropped")).toBe("not marked")
  })

  it("maps task #36's dedicated blank value, with the SAME copy", () => {
    // `"blank"` (migration `0040_marker_source_blank`) is the genuine student
    // blank, split out of `"missing"` so the backend can tell it from a
    // `--mcq-only` skip. The copy deliberately does not follow: what a student
    // should be told about each is a product decision and remains unmade, so
    // distinguishing them here would be this change inventing it. What must not
    // happen is the raw token reaching the chip, which is what a label written
    // as an explicit list of values would have done.
    expect(markerSourceLabel("blank")).toBe("not marked")
  })

  it("leaves deterministic/ai as the existing raw pass-through", () => {
    expect(markerSourceLabel("deterministic")).toBe("deterministic")
    expect(markerSourceLabel("ai")).toBe("ai")
  })
})

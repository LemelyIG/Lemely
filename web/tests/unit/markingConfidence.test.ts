import { describe, expect, it } from "vitest"
import {
  confidenceSummaryOf,
  confidenceTierFor,
  REVIEW_CONFIDENCE_THRESHOLD,
} from "@/lib/markingConfidence"

/*
 * P4.2 · The student's confidence bucketing must agree with the teacher's.
 *
 * The defect these pin: `PaperResult` used a 0.85 threshold it had invented,
 * while the backend and the teacher portal use 0.90. A mark between the two
 * numbers was described differently to the two people looking at the same
 * paper. `tests/test_design_tokens.py` pins the constant against the Python
 * definition; these pin the behaviour that hangs off it.
 */

describe("confidenceTierFor", () => {
  it("uses the backend's 0.90 review floor, not a frontend guess", () => {
    expect(REVIEW_CONFIDENCE_THRESHOLD).toBe(0.9)
    // The whole point: this value used to be called confident.
    expect(confidenceTierFor({ confidence: 0.87 })).toBe("uncertain")
    expect(confidenceTierFor({ confidence: 0.9 })).toBe("confident")
    expect(confidenceTierFor({ confidence: 0.899 })).toBe("uncertain")
  })

  it("lets an explicit review reason win at any confidence", () => {
    // Integrity checks set `reviewReason` without touching the score, so a
    // flagged question can be at 1.0 and still need a human.
    expect(confidenceTierFor({ confidence: 1, reviewReason: "Handwriting unclear" })).toBe(
      "needs-review",
    )
    expect(confidenceTierFor({ confidence: 0.2, reviewReason: "Answer off-scheme" })).toBe(
      "needs-review",
    )
  })

  it("US-039 MUST-FIX 2: an unflagged blank (needsTeacherReview: false) does not need review", () => {
    // `_build_blank_corrected` sets a `reviewReason` message purely so the
    // review queue/DB can tell a genuine blank apart from every other
    // blank-shaped state, while deliberately leaving `needsTeacherReview`
    // false -- the product owner's "unflagged zero" ruling. Before this fix,
    // `reviewReason` alone meant "needs review" for every case, so 8
    // unattempted parts on a paper rendered 8 warn-coloured "Needs review"
    // lines for questions the backend explicitly decided need none.
    expect(
      confidenceTierFor({
        reviewReason: "student left this question blank (0 awarded, no AI call made)",
        needsTeacherReview: false,
        confidence: 0,
        markerSource: "missing",
      }),
    ).not.toBe("needs-review")
  })

  it("US-039 finding G: a genuine blank is 'not-marked', not 'uncertain'", () => {
    // Wire values for `_build_blank_corrected` (`lemely/web/schemas.py`):
    // confidence 0.0, needsTeacherReview false, markerSource "missing". Before
    // this fix, 0.0 fell through the needs-review check (needsTeacherReview
    // is false) straight into the score check, and 0 < 0.9 read "uncertain" --
    // the same false claim ("the marker was unsure") one notch quieter than
    // "needs-review". A blank has no confidence, neither high nor low.
    expect(
      confidenceTierFor({
        confidence: 0,
        needsTeacherReview: false,
        markerSource: "missing",
        reviewReason: "student left this question blank (0 awarded, no AI call made)",
      }),
    ).toBe("not-marked")
    // "dropped" (US-038: extraction discarded a malformed answer) gets the
    // same treatment when it carries the same unflagged-zero shape.
    expect(
      confidenceTierFor({ confidence: 0, needsTeacherReview: false, markerSource: "dropped" }),
    ).toBe("not-marked")
    // Task #36: the value a real blank actually carries now
    // (`_build_blank_corrected`, migration `0040_marker_source_blank`). The
    // guard reads `markerScored`, so this arrives covered rather than needing
    // a tenth site to be found and edited.
    expect(
      confidenceTierFor({ confidence: 0, needsTeacherReview: false, markerSource: "blank" }),
    ).toBe("not-marked")
  })

  it("US-039 finding G: markerSource alone does not trigger not-marked", () => {
    // The gate is the unflagged-zero SHAPE (needsTeacherReview === false),
    // not the marker source in isolation -- a "missing"/"dropped" question
    // that DOES need review (needsTeacherReview: true, every pre-existing
    // 0.0 producer) must keep surfacing as "needs-review", not go quiet.
    expect(
      confidenceTierFor({
        confidence: 0,
        needsTeacherReview: true,
        markerSource: "missing",
        reviewReason: "Question could not be extracted",
      }),
    ).toBe("needs-review")
    // No markerSource at all (every caller that predates this field) must
    // keep behaving exactly as before: score-based bucketing.
    expect(confidenceTierFor({ confidence: 0, needsTeacherReview: false })).toBe("uncertain")
  })

  it("US-039 MUST-FIX 2: `needsTeacherReview: undefined` preserves today's behaviour", () => {
    // The whole reason this shape is safe: every existing caller that never
    // set `needsTeacherReview` must keep behaving exactly as before -- a
    // set `reviewReason` alone still wins.
    expect(confidenceTierFor({ reviewReason: "Handwriting unclear" })).toBe("needs-review")
    expect(
      confidenceTierFor({ reviewReason: "Handwriting unclear", needsTeacherReview: undefined }),
    ).toBe("needs-review")
  })

  it("US-039 MUST-FIX 2: an explicit needsTeacherReview: true still needs review", () => {
    expect(
      confidenceTierFor({ reviewReason: "Two answers given", needsTeacherReview: true }),
    ).toBe("needs-review")
  })

  it("stale-flag defect (S2 review): a settled self-review beats a frozen reviewReason", () => {
    // A resolved `low_confidence` queue row: `pendingTeacher: false` says no
    // teacher review is open for this question *right now*, and that wins
    // outright even though `reviewReason` -- the marker's frozen record of
    // why it was once flagged -- is still sitting there, unrewritten by
    // design. Before this fix there was no `pendingTeacher` signal at all,
    // so a self-reviewed, fully-settled question still read "needs-review"
    // forever.
    expect(
      confidenceTierFor({ reviewReason: "low confidence", pendingTeacher: false }),
    ).toBe("confident")
    // `pendingTeacher: true` (still open) behaves exactly as `reviewReason`
    // alone always has.
    expect(
      confidenceTierFor({ reviewReason: "low confidence", pendingTeacher: true }),
    ).toBe("needs-review")
    // `pendingTeacher` absent (a teacher-console grade, a live
    // `/student/correct` frame -- no queue to ask) must not change today's
    // behaviour for every source that never sends the field.
    expect(confidenceTierFor({ reviewReason: "low confidence" })).toBe("needs-review")
  })

  it("merge intersection: a blank with NO open queue row is still 'not-marked'", () => {
    // The row neither side's suite could hold, because neither side alone
    // produced it. `pendingTeacher: false` (develop: no review is open) and
    // the unflagged-blank shape (this branch) co-occur on every US-039 blank
    // once both exist: a blank is exempt from the queue BY DESIGN, so no row
    // is ever open for it.
    //
    // Resolving `confidenceTierFor` with develop's `pendingTeacher === false`
    // guard first returns "confident" here -- the marker is confident about a
    // question no marker read -- and leaves `not-marked` dead code. Strictly
    // worse than the "uncertain" finding G replaced. This is the assertion
    // that fails if the guard order is ever flipped back.
    expect(
      confidenceTierFor({
        reviewReason: "student left this question blank (0 awarded, no AI call made)",
        needsTeacherReview: false,
        confidence: 0,
        markerSource: "missing",
        pendingTeacher: false,
      }),
    ).toBe("not-marked")
  })

  it("merge intersection: not-marked-first does not capture a settled self-review", () => {
    // The mirror direction, and the row that could not be settled by reading
    // either file: putting `not-marked` first must not cost develop's fix. A
    // question a self-mark has settled has a REAL marker source ("ai"), so it
    // fails the `not-marked` gate, falls through to `pendingTeacher === false`
    // and still reads "confident".
    expect(
      confidenceTierFor({
        reviewReason: "low confidence",
        needsTeacherReview: false,
        confidence: 0.55,
        markerSource: "ai",
        pendingTeacher: false,
      }),
    ).toBe("confident")
  })

  it("merge intersection: a FLAGGED missing answer with an open row still needs review", () => {
    // `markerSource` alone is not the gate, and `pendingTeacher` does not
    // become one either: an extraction failure the backend flagged
    // (needsTeacherReview: true) falls past `not-marked` and keeps surfacing.
    expect(
      confidenceTierFor({
        reviewReason: "Question could not be extracted",
        needsTeacherReview: true,
        confidence: 0,
        markerSource: "missing",
        pendingTeacher: true,
      }),
    ).toBe("needs-review")
  })

  it("treats a missing score as confident rather than doubtful", () => {
    // The arguable call, made deliberately: MCQ marking is deterministic
    // string comparison and carries no score, so the alternative would flag
    // every question on a 40-question MCQ paper as uncertain.
    expect(confidenceTierFor({})).toBe("confident")
    expect(confidenceTierFor({ confidence: Number.NaN })).toBe("confident")
  })
})

describe("confidenceSummaryOf", () => {
  it("counts each question exactly once", () => {
    const summary = confidenceSummaryOf([
      { confidence: 0.98 },
      { confidence: 0.95 },
      { confidence: 0.6 },
      { confidence: 0.99, reviewReason: "Two answers given" },
    ])
    expect(summary).toEqual({ confident: 2, uncertain: 1, needsReview: 1, notMarked: 0 })
    expect(summary.confident + summary.uncertain + summary.needsReview + summary.notMarked).toBe(
      4,
    )
  })

  it("returns zeroes for a paper with no questions", () => {
    expect(confidenceSummaryOf([])).toEqual({
      confident: 0,
      uncertain: 0,
      needsReview: 0,
      notMarked: 0,
    })
  })

  it("US-039 finding G: a paper with 8 blanks reports 8 not-marked, not 8 uncertain", () => {
    // The exact scenario the finding names: before this fix, every one of
    // these 8 unattempted parts fell through to "uncertain" and the summary
    // strip read "8 uncertain" for questions no marker ever looked at.
    const blank = {
      confidence: 0,
      needsTeacherReview: false,
      markerSource: "missing",
      reviewReason: "student left this question blank (0 awarded, no AI call made)",
    }
    const questions = [
      { confidence: 0.95 },
      { confidence: 0.95 },
      ...Array.from({ length: 8 }, () => blank),
    ]
    const summary = confidenceSummaryOf(questions)
    expect(summary).toEqual({ confident: 2, uncertain: 0, needsReview: 0, notMarked: 8 })
  })
})

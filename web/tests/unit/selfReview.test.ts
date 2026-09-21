import { describe, expect, it } from "vitest"
import type {
  SelfReviewPending,
  SelfReviewRevealed,
  SelfReviewRevealedPoint,
} from "@/lib/selfReviewTypes"
import {
  ABSORBED_COPY,
  EMPTY_DRAFT,
  OUTCOME_LABEL,
  UNAVAILABLE_COPY,
  evidenceHint,
  isComplete,
  outcomeDetail,
  outcomeSummary,
  phaseOf,
  pointOutcome,
  setEvidence,
  setVerdict,
  summaryLine,
  toSubmission,
} from "@/lib/selfReview"

/*
 * Pure logic for the self-review panel (spec 2026-09-17). Every branch
 * carries its inverse so a helper that returns one thing unconditionally
 * cannot pass.
 */

const group = { isAlternative: false, isOptional: false, groupKey: null, groupMaxMarks: null }
const points = [
  { markPointId: "p1", ordinal: 0, markType: "M", tariff: 1, pointText: "Correct method", ...group },
  { markPointId: "p2", ordinal: 1, markType: "A", tariff: 1, pointText: "Answer to 3sf", ...group },
]

function pending(overrides: Partial<SelfReviewPending> = {}): SelfReviewPending {
  return {
    state: "not_started",
    attemptId: "a1",
    questionResultId: "q1",
    questionId: "1a",
    maxMarks: 2,
    evidenceRequired: false,
    points,
    ...overrides,
  }
}

function revealedPoint(overrides: Partial<SelfReviewRevealedPoint> = {}): SelfReviewRevealedPoint {
  return {
    ...points[0],
    awarded: false,
    studentSelfmark: true,
    studentEvidence: null,
    evidenceVerdict: null,
    markChanged: false,
    absorbedByGroup: false,
    judgeReason: null,
    ...overrides,
  }
}

function revealed(overrides: Partial<SelfReviewRevealed> = {}): SelfReviewRevealed {
  return {
    state: "settled",
    attemptId: "a1",
    questionResultId: "q1",
    questionId: "1a",
    maxMarks: 2,
    evidenceRequired: true,
    aiMarks: 1,
    effectiveMarks: 1,
    studentMarks: null,
    teacherSettled: false,
    pendingTeacher: false,
    submittedAt: "2026-09-18T10:00:00Z",
    points: [revealedPoint()],
    ...overrides,
  }
}

describe("draft editing", () => {
  it("records a verdict per point without mutating the previous draft", () => {
    const next = setVerdict(EMPTY_DRAFT, "p1", true)
    expect(next.verdicts).toEqual({ p1: true })
    expect(EMPTY_DRAFT.verdicts).toEqual({})
  })

  it("records evidence per point", () => {
    expect(setEvidence(EMPTY_DRAFT, "p2", "I wrote it").evidence).toEqual({ p2: "I wrote it" })
  })

  it("is complete only when every point has a boolean verdict", () => {
    expect(isComplete(EMPTY_DRAFT, points)).toBe(false)
    expect(isComplete(setVerdict(EMPTY_DRAFT, "p1", true), points)).toBe(false)
    const both = setVerdict(setVerdict(EMPTY_DRAFT, "p1", true), "p2", false)
    expect(isComplete(both, points)).toBe(true)
    expect(isComplete(both, [])).toBe(false)
  })
})

describe("toSubmission", () => {
  it("sends every point, trimming evidence and omitting it when blank", () => {
    let draft = setVerdict(setVerdict(EMPTY_DRAFT, "p1", true), "p2", false)
    draft = setEvidence(setEvidence(draft, "p1", "  see line 2  "), "p2", "   ")
    expect(toSubmission(draft, points)).toEqual({
      points: [
        { markPointId: "p1", earned: true, evidence: "see line 2" },
        { markPointId: "p2", earned: false },
      ],
    })
  })

  it("refuses an incomplete draft rather than sending a partial pass", () => {
    expect(() => toSubmission(setVerdict(EMPTY_DRAFT, "p1", true), points)).toThrow(
      /every point/i,
    )
  })
})

describe("phaseOf", () => {
  it("is not_started with no view or an untouched draft", () => {
    expect(phaseOf(undefined, EMPTY_DRAFT)).toBe("not_started")
    expect(phaseOf(pending(), EMPTY_DRAFT)).toBe("not_started")
  })

  it("is self_marking once any verdict is chosen", () => {
    expect(phaseOf(pending(), setVerdict(EMPTY_DRAFT, "p1", false))).toBe("self_marking")
  })

  it("mirrors the server state after submission regardless of the draft", () => {
    expect(phaseOf(revealed({ state: "revealed" }), setVerdict(EMPTY_DRAFT, "p1", true))).toBe(
      "revealed",
    )
    expect(phaseOf(revealed({ state: "settled" }), EMPTY_DRAFT)).toBe("settled")
  })
})

describe("pointOutcome", () => {
  it("agreed when the two verdicts match, whichever way", () => {
    expect(pointOutcome(revealedPoint({ awarded: true, studentSelfmark: true }), revealed())).toBe(
      "agreed",
    )
    expect(pointOutcome(revealedPoint({ awarded: false, studentSelfmark: false }), revealed())).toBe(
      "agreed",
    )
  })

  it("changed when the disagreement was granted", () => {
    expect(
      pointOutcome(revealedPoint({ markChanged: true, evidenceVerdict: "not_required" }), revealed()),
    ).toBe("changed")
  })

  it("pending only for an unjudged, evidenced claim while a teacher is waiting", () => {
    const unjudged = revealedPoint({ studentEvidence: "because", evidenceVerdict: null })
    expect(pointOutcome(unjudged, revealed({ pendingTeacher: true }))).toBe("pending")
    expect(pointOutcome(unjudged, revealed({ pendingTeacher: false }))).toBe("kept")
    // No evidence: nothing was ever sent to a judge, so nothing is pending.
    expect(pointOutcome(revealedPoint(), revealed({ pendingTeacher: true }))).toBe("kept")
  })

  it("kept for a rejected claim", () => {
    expect(
      pointOutcome(revealedPoint({ studentEvidence: "x", evidenceVerdict: "rejected" }), revealed()),
    ).toBe("kept")
  })
})

describe("outcome copy", () => {
  it("shows the judge's reason when there is one, in both directions", () => {
    const accepted = revealedPoint({
      markChanged: true,
      evidenceVerdict: "accepted",
      judgeReason: "The unit is there.",
    })
    expect(outcomeDetail(accepted, "changed", true)).toBe("The unit is there.")
    const rejected = revealedPoint({ evidenceVerdict: "rejected", judgeReason: "No unit at all." })
    expect(outcomeDetail(rejected, "kept", true)).toBe("No unit at all.")
  })

  it("explains a low-confidence grant and an unevidenced high-confidence claim", () => {
    expect(
      outcomeDetail(revealedPoint({ markChanged: true, evidenceVerdict: "not_required" }), "changed", false),
    ).toMatch(/not sure/)
    expect(outcomeDetail(revealedPoint(), "kept", true)).toMatch(/give a reason/)
    expect(outcomeDetail(revealedPoint(), "kept", false)).toBeNull()
    expect(outcomeDetail(revealedPoint({ awarded: true }), "agreed", true)).toBeNull()
  })

  it("explains a granted verdict its group absorbed, in either confidence band", () => {
    const absorbed = revealedPoint({ evidenceVerdict: "not_required", absorbedByGroup: true })
    expect(pointOutcome(absorbed, revealed())).toBe("kept")
    expect(outcomeDetail(absorbed, "kept", false)).toBe(ABSORBED_COPY)
    expect(outcomeDetail(absorbed, "kept", true)).toBe(ABSORBED_COPY)
  })

  it("summarises outcomes and the marks movement", () => {
    const view = revealed({
      aiMarks: 0,
      effectiveMarks: 2,
      studentMarks: 2,
      points: [
        revealedPoint({ markChanged: true, evidenceVerdict: "not_required" }),
        revealedPoint({ ...points[1], markChanged: true, evidenceVerdict: "not_required" }),
      ],
    })
    expect(outcomeSummary(view)).toEqual({ agreed: 0, changed: 2, kept: 0, pending: 0 })
    expect(summaryLine(view)).toBe("Your self-mark moved this question from 0 to 2 out of 2.")
    expect(summaryLine(revealed())).toBe("This question stays at 1 out of 2.")
    expect(summaryLine(revealed({ teacherSettled: true }))).toMatch(/teacher has already/)
  })

  it("names the evidence rule per confidence, and never an integrity flag", () => {
    expect(evidenceHint(true)).toMatch(/confident/)
    expect(evidenceHint(false)).toMatch(/your verdict counts/i)
    const allCopy = [
      evidenceHint(true),
      evidenceHint(false),
      UNAVAILABLE_COPY,
      ...Object.values(OUTCOME_LABEL),
    ].join(" ")
    expect(allCopy).not.toMatch(/plagiar|AI-generated|cheat/i)
    // REDESIGN-MISSION §3.2 item 10: no em dashes, no exclamation marks in copy.
    expect(allCopy).not.toMatch(/[—!]/)
  })
})

import { describe, expect, it } from "vitest"
import type {
  SelfReviewPendingPoint,
  SelfReviewRevealed,
  SelfReviewRevealedPoint,
} from "@/lib/selfReviewTypes"
import {
  ABSORBED_COPY,
  EMPTY_DRAFT,
  OUTCOME_LABEL,
  UNAVAILABLE_COPY,
  evidenceHint,
  groupLabel,
  groupPoints,
  isComplete,
  markWord,
  outcomeDetail,
  outcomeSummary,
  pointOutcome,
  setEvidence,
  setVerdict,
  summaryLine,
  toSubmission,
  type Groupable,
} from "@/lib/selfReview"

/*
 * Pure logic for the self-review panel (spec 2026-09-17). Every branch
 * carries its inverse so a helper that returns one thing unconditionally
 * cannot pass.
 */

/**
 * Compile-time guard for the invariant `selfReviewTypes.ts` documents in its
 * header comment: `awarded` must never appear on the pre-reveal point shape.
 * A regression that adds it here would type-check silently otherwise (Task
 * 12 review, SHOULD-FIX 3) — `npm run typecheck` fails if either assertion
 * below is wrong, since `tsconfig.test.json` includes `tests`.
 */
type HasAwarded<T> = "awarded" extends keyof T ? true : false
const _pendingHasNoVerdict: HasAwarded<SelfReviewPendingPoint> = false
const _revealedHasVerdict: HasAwarded<SelfReviewRevealedPoint> = true
void _pendingHasNoVerdict
void _revealedHasVerdict

const group = { isAlternative: false, isOptional: false, groupKey: null, groupMaxMarks: null }
const points = [
  { markPointId: "p1", ordinal: 0, markType: "M", tariff: 1, pointText: "Correct method", ...group },
  { markPointId: "p2", ordinal: 1, markType: "A", tariff: 1, pointText: "Answer to 3sf", ...group },
]

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

  it("only counts an actual boolean as a verdict, not merely a present key", () => {
    // A weaker `!== undefined` check would pass this; a string is not a
    // verdict (Task 12 review, NIT 3).
    const bothPresent = {
      ...EMPTY_DRAFT,
      verdicts: { p1: "true" as unknown as boolean, p2: false },
    }
    expect(isComplete(bothPresent, points)).toBe(false)
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

  it("gives no unearned 'not sure' explanation for a changed point outside the not_required/accepted states", () => {
    // `changed` is only reachable via markChanged, which today only follows
    // `not_required` or `accepted` (Task 12 review, NIT 1) — but the copy
    // must not assert "the marker was not sure" for a state that doesn't
    // say so.
    expect(
      outcomeDetail(revealedPoint({ markChanged: true, evidenceVerdict: "rejected" }), "changed", true),
    ).toBeNull()
  })

  it("tells the student a teacher will look, for the one point still unjudged", () => {
    const unjudged = revealedPoint({ studentEvidence: "because I carried the term", evidenceVerdict: null })
    expect(outcomeDetail(unjudged, "pending", true)).toMatch(/teacher/i)
  })

  it("explains a granted verdict its group absorbed, in either confidence band", () => {
    const absorbed = revealedPoint({ evidenceVerdict: "not_required", absorbedByGroup: true })
    expect(pointOutcome(absorbed, revealed())).toBe("kept")
    expect(outcomeDetail(absorbed, "kept", false)).toBe(ABSORBED_COPY)
    expect(outcomeDetail(absorbed, "kept", true)).toBe(ABSORBED_COPY)
  })

  it("says nothing false about ABSORBED_COPY: no cap claim, no 'already have' claim", () => {
    // Task 12 review SHOULD-FIX 1: in a mixed-direction group at net zero,
    // the granted point may be the ONE now carrying the mark a sibling just
    // dropped — so the copy must not say the group is at cap, and must not
    // say the student already holds the mark elsewhere.
    expect(ABSORBED_COPY).toMatch(/group/i)
    expect(ABSORBED_COPY).not.toMatch(/already earned all|already have|shares its mark/i)
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

  it("does not assert finality on the headline while a teacher is still going to look", () => {
    // Task 12 review SHOULD-FIX 2: `state: "revealed"` with `pendingTeacher`
    // true means the judge failed for one point, no marks moved, and a
    // `student_evidence_unjudged` row is open — a teacher may still move
    // this mark, so the headline must not read as final.
    const line = summaryLine(revealed({ pendingTeacher: true }))
    expect(line).not.toBe("This question stays at 1 out of 2.")
    expect(line).toMatch(/teacher/i)
    // Still true even when other points DID move the mark already.
    const linePartiallyMoved = summaryLine(revealed({ pendingTeacher: true, aiMarks: 0, effectiveMarks: 1 }))
    expect(linePartiallyMoved).toMatch(/teacher/i)
    expect(linePartiallyMoved).not.toMatch(/moved this question from/)
  })

  it("gives every outcome label a distinct, meaningful phrase", () => {
    // Task 12 review SHOULD-FIX 5: `toBe`/`toEqual` on the record alone
    // would pass for junk labels — assert the words carry the meaning.
    const values = Object.values(OUTCOME_LABEL)
    expect(new Set(values).size).toBe(values.length)
    expect(OUTCOME_LABEL.agreed).toMatch(/agree/i)
    expect(OUTCOME_LABEL.changed).toMatch(/applied|mark/i)
    expect(OUTCOME_LABEL.kept).toMatch(/did not change|stands|unchanged/i)
    expect(OUTCOME_LABEL.pending).toMatch(/teacher/i)
  })

  it("names the paper and the reason self-review is unavailable", () => {
    expect(UNAVAILABLE_COPY).toMatch(/not available/i)
    expect(UNAVAILABLE_COPY).toMatch(/paper/i)
  })

  it("names the evidence rule per confidence, and never an integrity flag", () => {
    expect(evidenceHint(true)).toMatch(/confident/)
    expect(evidenceHint(false)).toMatch(/your verdict counts/i)
    // Every string these helpers can put in front of a student, not a
    // hand-picked subset (Task 12 review, SHOULD-FIX 4: the previous scan
    // covered 6 of 13 emitted strings and let integrity-flag copy through).
    const allDetailStrings = [
      outcomeDetail(revealedPoint({ evidenceVerdict: "accepted" }), "changed", true),
      outcomeDetail(revealedPoint({ evidenceVerdict: "not_required" }), "changed", true),
      outcomeDetail(revealedPoint({ evidenceVerdict: "rejected" }), "kept", true),
      outcomeDetail(revealedPoint({ absorbedByGroup: true }), "kept", true),
      outcomeDetail(revealedPoint(), "kept", true),
      outcomeDetail(revealedPoint({ studentEvidence: "x" }), "pending", true),
    ].filter((s): s is string => s !== null)
    const allCopy = [
      evidenceHint(true),
      evidenceHint(false),
      UNAVAILABLE_COPY,
      ABSORBED_COPY,
      ...Object.values(OUTCOME_LABEL),
      ...allDetailStrings,
    ].join(" ")
    expect(allCopy).not.toMatch(/plagiar|AI-generated|cheat/i)
    // REDESIGN-MISSION §3.2 item 10: no em dashes, no exclamation marks in copy.
    expect(allCopy).not.toMatch(/[—!]/)
  })
})

/*
 * groupPoints / groupLabel (Task 13/14 review, IMP-6; re-review R-1/R-6). A
 * scheme group must present as ONE unit worth `groupMaxMarks`
 * (`selfReviewTypes.ts:29-33`, `schemas_student_self_review.py:36-40`),
 * never as its members' tariffs added up — an "any 2 from 4" pool of 1-mark
 * points is worth 2 marks, not 4. These assert over real point arrays, not
 * source text, because this is exactly the arithmetic a text gate cannot
 * check.
 *
 * R-1: the first pass of this block used `tariff: 1` in every case, where
 * marks and a select-count coincide by accident — the exact shape the bug it
 * was meant to catch is invisible in. `groupLabel` states only the group's
 * total worth now, never a count the wire cannot supply (`groupMaxMarks` is
 * documented server-side as "the most the group can contribute", not "how
 * many members you may claim" — `question_points.py:131-145`), so every case
 * below is checked with tariffs that are NOT all 1, plus a 3-member
 * alternative and a `maxMarks: 0` pool (a pool a preceding pool already
 * exhausted — `_group_points`' own docstring says this happens).
 */
function groupablePoint(overrides: Partial<Groupable> = {}): Groupable {
  return { markPointId: "p", groupKey: null, groupMaxMarks: null, tariff: 1, ...overrides }
}

describe("groupPoints / groupLabel", () => {
  it("collapses an either/or pair into one group worth its shared groupMaxMarks", () => {
    const pair = [
      groupablePoint({ markPointId: "p1", groupKey: "alt:1", groupMaxMarks: 1 }),
      groupablePoint({ markPointId: "p2", groupKey: "alt:1", groupMaxMarks: 1 }),
    ]
    const groups = groupPoints(pair)
    expect(groups).toHaveLength(1)
    expect(groups[0]!.kind).toBe("alternative")
    expect(groups[0]!.maxMarks).toBe(1)
    expect(groups[0]!.points).toHaveLength(2)
    expect(groupLabel(groups[0]!)).toBe("One of these, worth 1 mark in total")
  })

  it("collapses an any-N-from pool into one group worth groupMaxMarks, not the sum of tariffs", () => {
    const pool = [
      groupablePoint({ markPointId: "p1", groupKey: "pool:1", groupMaxMarks: 2 }),
      groupablePoint({ markPointId: "p2", groupKey: "pool:1", groupMaxMarks: 2 }),
      groupablePoint({ markPointId: "p3", groupKey: "pool:1", groupMaxMarks: 2 }),
      groupablePoint({ markPointId: "p4", groupKey: "pool:1", groupMaxMarks: 2 }),
    ]
    const groups = groupPoints(pool)
    expect(groups).toHaveLength(1)
    expect(groups[0]!.kind).toBe("pool")
    expect(groups[0]!.points).toHaveLength(4)
    expect(groups[0]!.maxMarks).toBe(2)
    // The whole point of IMP-6: four 1-mark points sum to 4, but the group is
    // only ever worth 2. A regression back to per-point tariffs would pass
    // the sum, not the group cap.
    expect(groups[0]!.maxMarks).not.toBe(pool.reduce((sum, p) => sum + p.tariff, 0))
    expect(groupLabel(groups[0]!)).toBe("These together, worth 2 marks in total")
  })

  it("keeps grouped and independent points on the same question as separate groups", () => {
    const mixed = [
      groupablePoint({ markPointId: "p1", groupKey: "alt:1", groupMaxMarks: 1 }),
      groupablePoint({ markPointId: "p2", groupKey: "alt:1", groupMaxMarks: 1 }),
      groupablePoint({ markPointId: "p3", groupKey: null, groupMaxMarks: null, tariff: 2 }),
    ]
    const groups = groupPoints(mixed)
    expect(groups).toHaveLength(2)
    expect(groups[0]!.kind).toBe("alternative")
    expect(groups[0]!.points.map((p) => p.markPointId)).toEqual(["p1", "p2"])
    expect(groups[1]!.kind).toBe("single")
    expect(groups[1]!.points.map((p) => p.markPointId)).toEqual(["p3"])
    expect(groups[1]!.maxMarks).toBe(2)
    expect(groupLabel(groups[1]!)).toBe("2 marks")
  })

  it("states the group's total worth, not a select-count, when member tariffs are NOT all 1 (Task 13/14 re-review, R-1)", () => {
    // Executed against the pre-fix helper, this exact case ("any 2 from 3,
    // 2-mark points, group cap 4") produced "Any 4 of these, 4 marks" —
    // reading `groupMaxMarks` (a mark total the scheme allows) as a count of
    // points to select. There is no select-count on the wire at all
    // (`SelfReviewPendingPointDTO` has no such field), so the only honest
    // claim is the group's worth.
    const threeTwoMarkers = [
      groupablePoint({ markPointId: "p1", groupKey: "pool:1", groupMaxMarks: 4, tariff: 2 }),
      groupablePoint({ markPointId: "p2", groupKey: "pool:1", groupMaxMarks: 4, tariff: 2 }),
      groupablePoint({ markPointId: "p3", groupKey: "pool:1", groupMaxMarks: 4, tariff: 2 }),
    ]
    const groups = groupPoints(threeTwoMarkers)
    expect(groups[0]!.points).toHaveLength(3)
    expect(groups[0]!.maxMarks).toBe(4)
    const label = groupLabel(groups[0]!)
    expect(label).toBe("These together, worth 4 marks in total")
    expect(label).not.toMatch(/any \d+ of these/i)
  })

  it("a 3-way alternative is worth its best single member, not 'either' (Task 13/14 re-review, R-1)", () => {
    // `_group_points` joins a run of consecutive is_alternative points into
    // one group, so alt groups of 3+ exist — "Either of these" (one of TWO)
    // is wrong for one of three. "One of these" holds for any group size.
    const threeWayAlt = [
      groupablePoint({ markPointId: "p1", groupKey: "alt:1", groupMaxMarks: 2, tariff: 2 }),
      groupablePoint({ markPointId: "p2", groupKey: "alt:1", groupMaxMarks: 2, tariff: 1 }),
      groupablePoint({ markPointId: "p3", groupKey: "alt:1", groupMaxMarks: 2, tariff: 2 }),
    ]
    const groups = groupPoints(threeWayAlt)
    expect(groups[0]!.points).toHaveLength(3)
    expect(groupLabel(groups[0]!)).toBe("One of these, worth 2 marks in total")
  })

  it("a pool a preceding pool already exhausted (maxMarks: 0) says so, not 'any 0 of these' (Task 13/14 re-review, R-1)", () => {
    // `_group_points`' own docstring: several pools in one question share the
    // question's leftover, consuming it in scheme order, so a later pool can
    // end capped at 0. The student still owes a verdict for every point
    // (the POST contract is unchanged), so the copy must not read as if
    // there is nothing there to mark — only that no further marks are on
    // offer for it.
    const exhausted = [
      groupablePoint({ markPointId: "p1", groupKey: "pool:2", groupMaxMarks: 0, tariff: 1 }),
      groupablePoint({ markPointId: "p2", groupKey: "pool:2", groupMaxMarks: 0, tariff: 1 }),
    ]
    const groups = groupPoints(exhausted)
    expect(groups[0]!.maxMarks).toBe(0)
    const label = groupLabel(groups[0]!)
    expect(label).not.toMatch(/any 0 of these/i)
    expect(label).toMatch(/no further marks/i)
  })

  /*
   * The next two cases are defence-in-depth, not specified behaviour: the
   * backend prunes a one-member group entirely (`_group_points` /
   * `question_points.py:173` only keeps groups with `len(members) > 1`, so
   * a lone-member group is written as `(None, None)` — a non-null `groupKey`
   * always has >= 2 members) and 404s the whole question rather than send a
   * `groupKey` with a null `groupMaxMarks` (`points_are_settleable`,
   * `self_review_repo.py:762-768`), which `SelfReviewPanel` renders as
   * `UNAVAILABLE_COPY` before `groupPoints` ever runs. Neither shape should
   * reach the panel in production, so neither case asserts a user-facing
   * `groupLabel` string as if it were the designed copy (Task 13/14
   * re-review, R-6) — only the structural properties `groupPoints` itself
   * is responsible for.
   */
  it("(defensive) a group of one still groups by key rather than falling back to a single-point shape", () => {
    const lone = [groupablePoint({ markPointId: "p1", groupKey: "pool:1", groupMaxMarks: 3, tariff: 1 })]
    const groups = groupPoints(lone)
    expect(groups).toHaveLength(1)
    expect(groups[0]!.kind).toBe("pool")
    expect(groups[0]!.points).toHaveLength(1)
    expect(groups[0]!.maxMarks).toBe(3)
  })

  it("(defensive) falls back to the point's own tariff when a grouped point carries a null groupMaxMarks", () => {
    const defective = [
      groupablePoint({ markPointId: "p1", groupKey: "pool:1", groupMaxMarks: null, tariff: 2 }),
    ]
    const groups = groupPoints(defective)
    expect(groups[0]!.maxMarks).toBe(2)
  })

  it("markWord pluralises correctly at 1 and elsewhere", () => {
    expect(markWord(1)).toBe("mark")
    expect(markWord(0)).toBe("marks")
    expect(markWord(2)).toBe("marks")
  })
})

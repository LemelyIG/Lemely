### Task 12: Wire types and the pure self-review state helpers

**Files:**
- Create: `web/src/lib/selfReviewTypes.ts`
- Create: `web/src/lib/selfReview.ts`
- Test: `web/tests/unit/selfReview.test.ts` (create)

**Interfaces:**
- Consumes: the wire shapes of Task 8.
- Produces (`web/src/lib/selfReviewTypes.ts`): `EvidenceVerdict`, `SelfReviewPendingPoint`, `SelfReviewRevealedPoint`, `SelfReviewPending`, `SelfReviewRevealed`, `SelfReview`, `SelfReviewPointVerdict`, `SelfReviewSubmission`.
- Produces (`web/src/lib/selfReview.ts`): `SelfReviewPhase`, `SelfReviewDraft`, `EMPTY_DRAFT`, `setVerdict(draft, markPointId, earned)`, `setEvidence(draft, markPointId, text)`, `isComplete(draft, points)`, `toSubmission(draft, points)`, `phaseOf(view, draft)`, `PointOutcome`, `pointOutcome(point, view)`, `outcomeSummary(view)`, `OUTCOME_LABEL`, `outcomeDetail(point, outcome, evidenceRequired)`, `evidenceHint(evidenceRequired)`, `summaryLine(view)`, `UNAVAILABLE_COPY`. Task 14 renders exactly these.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/selfReview.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import type {
  SelfReviewPending,
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
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && npx vitest run tests/unit/selfReview.test.ts
```

Expected: FAIL — `Cannot find module '@/lib/selfReview'`.

- [ ] **Step 3: Write the types**

Create `web/src/lib/selfReviewTypes.ts`:

```ts
/*
 * TS interfaces mirroring `lemely/web/schemas_student_self_review.py`
 * (student self-review, spec 2026-09-17). camelCase to match the wire.
 *
 * Two shapes, deliberately: `SelfReviewPending` is what the server sends
 * BEFORE the student commits to their own verdicts and its point type has no
 * `awarded` at all. The verdict exists only on `SelfReviewRevealed`. If a
 * field named `awarded` ever appears on the pending shape here, the backend
 * contract has been broken, not extended.
 */

export type EvidenceVerdict = "accepted" | "rejected" | "not_required"

export interface SelfReviewPendingPoint {
  markPointId: string
  ordinal: number
  /** `MathMarkType` letter (M/A/B/...) or null for non-maths questions. */
  markType: string | null
  tariff: number
  pointText: string
  isAlternative: boolean
  isOptional: boolean
  /**
   * Scheme group, derived server-side at correction time (Task 6a): `alt:n`
   * for an either/or run, `pool:n` for an "any N from" pool, null when the
   * point stands alone. Points sharing a key are one unit worth at most
   * `groupMaxMarks` — never render them as independently earnable.
   */
  groupKey: string | null
  groupMaxMarks: number | null
}

export interface SelfReviewRevealedPoint extends SelfReviewPendingPoint {
  awarded: boolean
  studentSelfmark: boolean
  studentEvidence: string | null
  evidenceVerdict: EvidenceVerdict | null
  markChanged: boolean
  /** The verdict was accepted but its group was already at its worth, so no mark moved (Task 6b). */
  absorbedByGroup: boolean
  judgeReason: string | null
}

interface SelfReviewBase {
  attemptId: string
  questionResultId: string
  questionId: string
  maxMarks: number
  /**
   * True when the marker was confident: a self-mark alone changes nothing,
   * and a written reason is what unlocks a (lenient) judge. False when the
   * marker was unsure: the student's verdict counts, reason optional.
   */
  evidenceRequired: boolean
}

export interface SelfReviewPending extends SelfReviewBase {
  state: "not_started"
  points: SelfReviewPendingPoint[]
}

export interface SelfReviewRevealed extends SelfReviewBase {
  /** `revealed` while a teacher still has to look at an unjudged claim. */
  state: "revealed" | "settled"
  aiMarks: number
  effectiveMarks: number
  studentMarks: number | null
  teacherSettled: boolean
  pendingTeacher: boolean
  submittedAt: string
  points: SelfReviewRevealedPoint[]
}

export type SelfReview = SelfReviewPending | SelfReviewRevealed

export interface SelfReviewPointVerdict {
  markPointId: string
  earned: boolean
  evidence?: string
}

/** `POST` body: a verdict for EVERY point. Partial passes are refused (422). */
export interface SelfReviewSubmission {
  points: SelfReviewPointVerdict[]
}
```

- [ ] **Step 4: Write the helpers**

Create `web/src/lib/selfReview.ts`:

```ts
import type {
  SelfReview,
  SelfReviewRevealed,
  SelfReviewRevealedPoint,
  SelfReviewSubmission,
} from "./selfReviewTypes"

/*
 * Pure state for the self-review panel (spec 2026-09-17), kept out of the
 * component so it is testable without jsdom (`web/vitest.config.ts` is
 * Node-only). The panel in `portals/student/components/SelfReviewPanel.tsx`
 * renders exactly what these return.
 *
 * Phases: `not_started` -> `self_marking` (client-only: the student has begun
 * choosing verdicts) -> `revealed` / `settled` (the server's own states).
 */

export type SelfReviewPhase = "not_started" | "self_marking" | "revealed" | "settled"

export interface SelfReviewDraft {
  readonly verdicts: Readonly<Record<string, boolean>>
  readonly evidence: Readonly<Record<string, string>>
}

export const EMPTY_DRAFT: SelfReviewDraft = { verdicts: {}, evidence: {} }

export function setVerdict(
  draft: SelfReviewDraft,
  markPointId: string,
  earned: boolean,
): SelfReviewDraft {
  return { ...draft, verdicts: { ...draft.verdicts, [markPointId]: earned } }
}

export function setEvidence(
  draft: SelfReviewDraft,
  markPointId: string,
  text: string,
): SelfReviewDraft {
  return { ...draft, evidence: { ...draft.evidence, [markPointId]: text } }
}

/** Every point has a verdict. The server refuses anything less (422). */
export function isComplete(
  draft: SelfReviewDraft,
  points: readonly { markPointId: string }[],
): boolean {
  return (
    points.length > 0 && points.every((p) => typeof draft.verdicts[p.markPointId] === "boolean")
  )
}

export function toSubmission(
  draft: SelfReviewDraft,
  points: readonly { markPointId: string }[],
): SelfReviewSubmission {
  if (!isComplete(draft, points)) {
    throw new Error("Every point needs a verdict before submitting")
  }
  return {
    points: points.map((p) => {
      const earned = draft.verdicts[p.markPointId] as boolean
      const evidence = (draft.evidence[p.markPointId] ?? "").trim()
      return evidence ? { markPointId: p.markPointId, earned, evidence } : { markPointId: p.markPointId, earned }
    }),
  }
}

export function phaseOf(view: SelfReview | undefined, draft: SelfReviewDraft): SelfReviewPhase {
  if (!view) return "not_started"
  if (view.state !== "not_started") return view.state
  return Object.keys(draft.verdicts).length > 0 ? "self_marking" : "not_started"
}

export type PointOutcome = "agreed" | "changed" | "kept" | "pending"

/**
 * `pending` is narrow on purpose: only a claim that was actually sent for
 * judging (it carried evidence), came back unjudged, and has an open teacher
 * row behind it. A bare disagreement with no reason was never pending.
 */
export function pointOutcome(
  point: SelfReviewRevealedPoint,
  view: Pick<SelfReviewRevealed, "pendingTeacher">,
): PointOutcome {
  if (point.studentSelfmark === point.awarded) return "agreed"
  if (point.markChanged) return "changed"
  if (view.pendingTeacher && point.evidenceVerdict === null && point.studentEvidence !== null) {
    return "pending"
  }
  return "kept"
}

export function outcomeSummary(view: SelfReviewRevealed): Record<PointOutcome, number> {
  const summary: Record<PointOutcome, number> = { agreed: 0, changed: 0, kept: 0, pending: 0 }
  for (const point of view.points) summary[pointOutcome(point, view)] += 1
  return summary
}

export const OUTCOME_LABEL: Record<PointOutcome, string> = {
  agreed: "You and the marker agree",
  changed: "Your mark was applied",
  kept: "This point's mark did not change",
  pending: "A teacher will look at this",
}

/**
 * A granted verdict the scheme group could not pay out (Task 6b's
 * `absorbedByGroup`). Deliberately direction-agnostic and non-causal: in a
 * mixed-direction group (one point claimed up, another disclaimed down, net
 * zero) the granted point is not "sharing" a mark a sibling already has —
 * it may be the very point now carrying the mark a sibling just dropped.
 * `absorbedByGroup` only tells us the group's own cap didn't move, so that
 * is all this line asserts. (Task 12 review, SHOULD-FIX 1.)
 */
export const ABSORBED_COPY =
  "Accepted, but this point is grouped with others on this question, so the group's total did not change."

/** One short line under a point, or null when the label says it all. */
export function outcomeDetail(
  point: SelfReviewRevealedPoint,
  outcome: PointOutcome,
  evidenceRequired: boolean,
): string | null {
  switch (outcome) {
    case "agreed":
      return null
    case "changed":
      if (point.evidenceVerdict === "accepted") return point.judgeReason ?? "Your reason was accepted."
      if (point.evidenceVerdict === "not_required") {
        return "The marker was not sure about this question, so your verdict counts."
      }
      return null
    case "kept":
      if (point.absorbedByGroup) return ABSORBED_COPY
      if (point.evidenceVerdict === "rejected") return point.judgeReason ?? "Your reason was not accepted."
      return evidenceRequired ? "To challenge a confident mark you need to give a reason." : null
    case "pending":
      return "Your reason could not be checked automatically. A teacher will look at it."
  }
}

export function evidenceHint(evidenceRequired: boolean): string {
  return evidenceRequired
    ? "The marker was confident here. To challenge a point, say what in your answer earns it."
    : "The marker was not sure about this question, so your verdict counts. Adding a reason is optional."
}

export function summaryLine(view: SelfReviewRevealed): string {
  if (view.teacherSettled) {
    return "A teacher has already reviewed this question, so their mark stands."
  }
  if (view.pendingTeacher) {
    return `This question is at ${view.effectiveMarks} out of ${view.maxMarks} while a teacher looks at one of your reasons.`
  }
  if (view.effectiveMarks !== view.aiMarks) {
    return `Your self-mark moved this question from ${view.aiMarks} to ${view.effectiveMarks} out of ${view.maxMarks}.`
  }
  return `This question stays at ${view.effectiveMarks} out of ${view.maxMarks}.`
}

/**
 * Shown when the server has no point rows for the question (404): a paper
 * corrected before the per-point breakdown existed, or a quiz. Said plainly
 * rather than leaving a student to wonder why one paper offers this and an
 * older one does not (spec "Open items").
 */
export const UNAVAILABLE_COPY =
  "Self-review is not available for this paper. It is offered on papers marked after the per-point breakdown was introduced."
```

- [ ] **Step 5: Run the tests, typecheck and lint**

```bash
cd web && npx vitest run tests/unit/selfReview.test.ts && npm run typecheck && npm run lint
```

Expected: 24 tests passed; typecheck and lint clean.

- [ ] **Step 6: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add web/src/lib/selfReviewTypes.ts web/src/lib/selfReview.ts web/tests/unit/selfReview.test.ts
git commit -S -m "feat(web): self-review wire types and pure draft/outcome helpers"
```

---


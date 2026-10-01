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
  /** I6: the marker's own verdict. Null on the legacy marking path. */
  verdict: "awarded" | "withheld" | "unverifiable" | null
  /** The marker's verbatim quote from this student's own answer. `""` when none. */
  evidenceSpan: string
  /** I7: this point was re-marked using the student's earlier value, so one slip did not cascade. */
  ecfApplied: boolean
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

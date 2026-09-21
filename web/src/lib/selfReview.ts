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

/*
 * Scheme groups (Task 13/14 review, IMP-6). `groupKey`/`groupMaxMarks` mark
 * points that share one scheme pool — an either/or pair (`alt:n`) or an
 * "any N from" pool (`pool:n`) — worth `groupMaxMarks` TOGETHER, never
 * individually: both wire contracts say so (`selfReviewTypes.ts:29-33`,
 * `lemely/web/schemas_student_self_review.py:36-40`). The panel's first
 * shipped version rendered one full-tariff `RadioGroup` per point regardless
 * of `groupKey`, which showed a 4-point "any 2 from 4" pool as four separate
 * 1-mark questions, implying 4 marks on offer where only 2 could ever be
 * paid. `groupPoints` collapses points sharing a key into one group with the
 * group's own worth stated once (`groupLabel`); the per-point radios still
 * render inside it, so the POST still carries a verdict for every point.
 *
 * Pure and here, not in the component, for the same reason every other
 * helper in this file is: this is the arithmetic that decides what a
 * student is told a group is worth, and it needs real assertions over real
 * inputs (`selfReview.test.ts`), not a source-text gate over JSX.
 */

export type PointGroupKind = "single" | "alternative" | "pool"

export interface PointGroup<P> {
  key: string | null
  points: readonly P[]
  maxMarks: number
  kind: PointGroupKind
}

/** Points a point must at least carry to be grouped. */
export interface Groupable {
  markPointId: string
  groupKey: string | null
  groupMaxMarks: number | null
  tariff: number
}

/**
 * Collapses points sharing a `groupKey` into one group, in the order they
 * first appear (server order is already ordinal-ordered — spec "Open
 * items", `attempts.py:262`). A point with no `groupKey` is its own
 * single-point group, so both shapes render through one code path. A
 * grouped point with a `null groupMaxMarks` (a defect the server should
 * never produce, but not one this helper should silently zero out) falls
 * back to its own tariff rather than claiming the group is worth nothing.
 */
export function groupPoints<P extends Groupable>(points: readonly P[]): PointGroup<P>[] {
  const groups: PointGroup<P>[] = []
  const byKey = new Map<string, PointGroup<P>>()
  for (const point of points) {
    if (!point.groupKey) {
      groups.push({ key: null, points: [point], maxMarks: point.tariff, kind: "single" })
      continue
    }
    const existing = byKey.get(point.groupKey)
    if (existing) {
      ;(existing.points as P[]).push(point)
      continue
    }
    const created: PointGroup<P> = {
      key: point.groupKey,
      points: [point],
      maxMarks: point.groupMaxMarks ?? point.tariff,
      kind: point.groupKey.startsWith("alt:") ? "alternative" : "pool",
    }
    byKey.set(point.groupKey, created)
    groups.push(created)
  }
  return groups
}

function markWord(marks: number): string {
  return marks === 1 ? "mark" : "marks"
}

/** "3 marks" for a standalone point; "Either of these, 1 mark" / "Any 2 of
 * these, 2 marks" for a scheme group — what the student is told the group
 * (or lone point) is worth, stated once rather than per point. */
export function groupLabel(group: Pick<PointGroup<unknown>, "kind" | "maxMarks">): string {
  if (group.kind === "single") return `${group.maxMarks} ${markWord(group.maxMarks)}`
  const verb = group.kind === "alternative" ? "Either of these" : `Any ${group.maxMarks} of these`
  return `${verb}, ${group.maxMarks} ${markWord(group.maxMarks)}`
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

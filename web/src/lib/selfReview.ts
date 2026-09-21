import type {
  SelfReviewRevealed,
  SelfReviewRevealedPoint,
  SelfReviewSubmission,
} from "./selfReviewTypes"

/*
 * Pure state for the self-review panel (spec 2026-09-17), kept out of the
 * component so it is testable without jsdom (`web/vitest.config.ts` is
 * Node-only). The panel in `portals/student/components/SelfReviewPanel.tsx`
 * renders exactly what these return.
 */

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

export function markWord(marks: number): string {
  return marks === 1 ? "mark" : "marks"
}

/**
 * What the student is told the group (or lone point) is worth, stated once
 * rather than per point: "3 marks" for a standalone point, "One of these,
 * worth 1 mark in total" / "These together, worth 2 marks in total" for a
 * scheme group.
 *
 * Task 13/14 re-review, R-1: the wire carries `groupMaxMarks` (a mark
 * total) and no select-count at all (`SelfReviewPendingPointDTO` has no
 * field for "pick N") — `_group_points` (`question_points.py:131-145`)
 * documents `groupMaxMarks` as "the most the group can contribute", not how
 * many of its members may be claimed. An earlier version of this function
 * read `groupMaxMarks` as a count ("Any N of these, N marks"), which is only
 * correct by coincidence when every member's tariff is 1 (the case every
 * test in the first pass used). Executed against backend-shaped inputs it
 * produced "Any 4 of these, 4 marks" for a 3-member pool of 2-mark points,
 * "Any 0 of these, 0 marks" for a pool a preceding pool had already
 * exhausted (`_group_points`' own docstring: pools sharing a question's
 * leftover can end capped at 0), and "Either of these" for a 3-way
 * alternative (`_group_points` joins a run of consecutive `is_alternative`
 * points into one group, so alt groups of 3+ exist — "either" means one of
 * two). This version states only what the data actually supports: the
 * group's total worth, never a count the client cannot know.
 */
export function groupLabel(group: Pick<PointGroup<unknown>, "kind" | "maxMarks">): string {
  if (group.kind === "single") return `${group.maxMarks} ${markWord(group.maxMarks)}`
  if (group.maxMarks === 0) return "These points are worth no further marks on this question."
  const lead = group.kind === "alternative" ? "One of these" : "These together"
  return `${lead}, worth ${group.maxMarks} ${markWord(group.maxMarks)} in total`
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

/*
 * Draft persistence (Task 13/14 review, SF-3/R-5). `QuestionRow`'s expanded
 * slot only renders `children` while `open` is true
 * (`question-row.tsx:186`), so collapsing the row unmounts
 * `SelfReviewPanel` and a plain `useState` draft would be silently
 * destroyed. `sessionStorage`, keyed per question, survives that unmount
 * for the life of the tab. The key format lives here, not in the panel, so
 * both the write side (the panel, on every edit) and the clear side (the
 * mutation hook's `onSuccess`, which is guaranteed to run even if the panel
 * has already unmounted — a per-`mutate()`-call callback is not) agree on
 * one spelling instead of duplicating it.
 */

const DRAFT_STORAGE_PREFIX = "lemely:self-review-draft:"

export function draftStorageKey(attemptId: string, questionResultId: string): string {
  return `${DRAFT_STORAGE_PREFIX}${attemptId}:${questionResultId}`
}

/** Wrapped: a private window, cleared site data, or storage genuinely
 * disabled must degrade quietly, never throw. */
export function clearDraft(attemptId: string, questionResultId: string): void {
  try {
    sessionStorage.removeItem(draftStorageKey(attemptId, questionResultId))
  } catch {
    // Nothing to clean up if storage was never writable.
  }
}

/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { Radio, RadioGroup } from "@/components/ui/radio"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/components/ui/toast"
import { ApiError } from "@/lib/api"
import { useSelfReview, useSubmitSelfReview } from "@/lib/hooks/useSelfReviewApi"
import {
  EMPTY_DRAFT,
  OUTCOME_LABEL,
  UNAVAILABLE_COPY,
  evidenceHint,
  isComplete,
  outcomeDetail,
  outcomeSummary,
  pointOutcome,
  setEvidence,
  setVerdict,
  summaryLine,
  toSubmission,
  type PointOutcome,
  type SelfReviewDraft,
} from "@/lib/selfReview"
import type {
  SelfReviewPending,
  SelfReviewPendingPoint,
  SelfReviewRevealed,
  SelfReviewRevealedPoint,
} from "@/lib/selfReviewTypes"

/*
 * Student self-review of one marked question (spec 2026-09-17), rendered in
 * a `QuestionRow`'s expanded slot on `PaperResult`.
 *
 * The panel never decides anything. Before submission the server sends no
 * verdict at all (`SelfReviewPending` has no `awarded`), so there is nothing
 * here to hide; after it, the server has already applied the authority rule
 * and this renders the outcome. One pass per question is enforced server-side
 * (a second POST is a 409), and the form disappears the moment the first one
 * succeeds because the cached view flips to `revealed`/`settled`.
 *
 * Copy: no integrity flag is ever named here (QUALITY-BAR.md), and per
 * REDESIGN-MISSION §3.2 item 10 there are no em dashes or exclamation marks.
 *
 * Errors reuse the catalogue's C-11 state family instead of a bare paragraph:
 * `EmptyState` (neutral tone) for "not offered on this paper" and `ErrorState`
 * (amber, per PRODUCT.md's "avoid red-heavy error states") for a genuine load
 * failure, both `compact` for a slot this size.
 *
 * Scheme groups (Task 13/14 review, IMP-6): `groupKey`/`groupMaxMarks` mark
 * points that share one scheme pool (an either/or pair, an "any N from")
 * worth `groupMaxMarks` together, never individually — both wire contracts
 * say so (`selfReviewTypes.ts`, `schemas_student_self_review.py`). The first
 * shipped version of this panel rendered one full-tariff `RadioGroup` per
 * point regardless of `groupKey`, which showed a 4-point "any 2 from 4" pool
 * as four separate 1-mark questions, implying 4 marks were on offer where
 * only 2 could ever be paid. `groupPoints` below collapses points sharing a
 * key into one card with the group's own worth stated once; the per-point
 * radios still render inside it, so the POST still carries a verdict for
 * every point (`SelfReviewSubmissionDTO` is unchanged).
 *
 * The draft (Task 13/14 review, SF-3) is persisted to `sessionStorage`, not
 * just component state: `QuestionRow`'s expanded slot only renders `children`
 * while `open` is true (`question-row.tsx:186`), so collapsing the row
 * unmounts this component and a plain `useState` draft would be silently
 * destroyed, taking up to 100 radio choices and 2000 characters of written
 * evidence per point with it. `sessionStorage` survives that unmount for the
 * life of the tab without needing `PaperResult` to lift and thread the state
 * through `QuestionList`/`QuestionRow` for a screen that does not otherwise
 * need to know about drafts.
 */

const OUTCOME_TONE: Record<PointOutcome, "ok" | "warn" | "neutral" | "info"> = {
  agreed: "neutral",
  changed: "ok",
  kept: "warn",
  pending: "info",
}

function verdictValue(earned: boolean | undefined): string | undefined {
  if (earned === undefined) return undefined
  return earned ? "earned" : "missed"
}

function markWord(marks: number): string {
  return marks === 1 ? "mark" : "marks"
}

/** One scheme-group's worth, shown once for the group rather than repeated
 * (and overstated) per point — see the module header, IMP-6. */
interface PointGroup<P> {
  key: string | null
  points: readonly P[]
  maxMarks: number
  kind: "single" | "alternative" | "pool"
}

/**
 * Collapses points sharing a `groupKey` into one group, in the order they
 * first appear (server order is already ordinal-ordered — spec "Open items",
 * `attempts.py:262`). A point with no `groupKey` is its own single-point
 * group so the two shapes render through one code path.
 */
export function groupPoints<
  P extends { markPointId: string; groupKey: string | null; groupMaxMarks: number | null; tariff: number },
>(points: readonly P[]): PointGroup<P>[] {
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

/** "3 marks" for a standalone point; "Either of these, 1 mark" / "Any 2 of
 * these, 2 marks" for a scheme group. */
function groupLabel(group: PointGroup<{ tariff: number }>): string {
  if (group.kind === "single") return `${group.maxMarks} ${markWord(group.maxMarks)}`
  const verb = group.kind === "alternative" ? "Either of these" : `Any ${group.maxMarks} of these`
  return `${verb}, ${group.maxMarks} ${markWord(group.maxMarks)}`
}

const DRAFT_STORAGE_PREFIX = "lemely:self-review-draft:"

function draftStorageKey(attemptId: string, questionResultId: string): string {
  return `${DRAFT_STORAGE_PREFIX}${attemptId}:${questionResultId}`
}

/** Reads a saved draft back for the initial `useState` value. Wrapped: a
 * private window, cleared site data, or storage genuinely disabled must
 * still render the ordinary empty form, not throw. */
function readSavedDraft(attemptId: string, questionResultId: string): SelfReviewDraft {
  try {
    const raw = sessionStorage.getItem(draftStorageKey(attemptId, questionResultId))
    if (!raw) return EMPTY_DRAFT
    const parsed = JSON.parse(raw) as SelfReviewDraft
    return parsed && typeof parsed === "object" && parsed.verdicts && parsed.evidence
      ? parsed
      : EMPTY_DRAFT
  } catch {
    return EMPTY_DRAFT
  }
}

function saveDraft(attemptId: string, questionResultId: string, draft: SelfReviewDraft): void {
  try {
    sessionStorage.setItem(draftStorageKey(attemptId, questionResultId), JSON.stringify(draft))
  } catch {
    // Storage full or disabled: the draft simply does not survive a
    // collapse/reopen this time, same as before this fix existed.
  }
}

function clearDraft(attemptId: string, questionResultId: string): void {
  try {
    sessionStorage.removeItem(draftStorageKey(attemptId, questionResultId))
  } catch {
    // Nothing to clean up if storage was never writable.
  }
}

export function SelfReviewPanel({
  attemptId,
  questionResultId,
}: {
  attemptId: string
  questionResultId: string
}) {
  const query = useSelfReview(attemptId, questionResultId)
  const submit = useSubmitSelfReview()
  const { toast } = useToast()
  const [draft, setDraft] = useState<SelfReviewDraft>(() =>
    readSavedDraft(attemptId, questionResultId),
  )

  const updateDraft = (next: SelfReviewDraft) => {
    setDraft(next)
    saveDraft(attemptId, questionResultId, next)
  }

  if (query.isPending) return <ListSkeleton rows={2} />
  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 404) {
      return (
        <div data-testid="self-review-unavailable">
          <EmptyState compact heading={UNAVAILABLE_COPY} />
        </div>
      )
    }
    return (
      <ErrorState
        compact
        heading="We couldn't load the self-review for this question."
        action={{ label: "Try again", onClick: () => void query.refetch() }}
        data-testid="self-review-error"
      />
    )
  }

  const view = query.data
  if (view.state === "not_started") {
    return (
      <PendingForm
        view={view}
        draft={draft}
        onDraft={updateDraft}
        submitting={submit.isPending}
        onSubmit={() =>
          submit.mutate(
            { attemptId, questionResultId, submission: toSubmission(draft, view.points) },
            {
              onSuccess: () => clearDraft(attemptId, questionResultId),
              onError: (error) =>
                toast({
                  title:
                    error instanceof ApiError && error.status === 409
                      ? "You have already self-marked this question. Showing the result."
                      : "We couldn't submit your self-mark. Please try again.",
                }),
            },
          )
        }
      />
    )
  }
  return <RevealedOutcome view={view} />
}

function PendingForm({
  view,
  draft,
  onDraft,
  submitting,
  onSubmit,
}: {
  view: SelfReviewPending
  draft: SelfReviewDraft
  onDraft: (next: SelfReviewDraft) => void
  submitting: boolean
  onSubmit: () => void
}) {
  const complete = isComplete(draft, view.points)
  const groups = groupPoints<SelfReviewPendingPoint>(view.points)
  return (
    <form
      className="flex flex-col gap-4"
      data-testid="self-review-form"
      onSubmit={(event) => {
        event.preventDefault()
        if (complete && !submitting) onSubmit()
      }}
    >
      <div className="flex flex-col gap-1">
        <h3 className="text-label text-ink">Mark your own answer first</h3>
        <p className="max-w-[56ch] text-pretty text-body-sm text-ink-muted">
          {evidenceHint(view.evidenceRequired)} The marker's verdict is revealed once you submit,
          and you can only do this once.
        </p>
      </div>
      {groups.map((group) => (
        <div
          key={group.key ?? group.points[0]!.markPointId}
          className="flex flex-col gap-3 rounded-md bg-paper-sunk px-3.5 py-3"
        >
          {group.kind !== "single" ? (
            <p className="text-label text-ink-muted">{groupLabel(group)}</p>
          ) : null}
          {group.points.map((point) => (
            <div key={point.markPointId} className="flex flex-col gap-2">
              <RadioGroup
                label={
                  group.kind === "single"
                    ? `${point.pointText} (${point.tariff} ${markWord(point.tariff)})`
                    : point.pointText
                }
                value={verdictValue(draft.verdicts[point.markPointId])}
                onValueChange={(value) =>
                  onDraft(setVerdict(draft, point.markPointId, value === "earned"))
                }
                orientation="horizontal"
              >
                <Radio value="earned" label="I earned this" />
                <Radio value="missed" label="I did not earn this" />
              </RadioGroup>
              <Textarea
                label={
                  view.evidenceRequired ? "Why? (needed to challenge the marker)" : "Why? (optional)"
                }
                hint={view.evidenceRequired ? undefined : "Up to 2000 characters"}
                rows={2}
                maxLength={2000}
                value={draft.evidence[point.markPointId] ?? ""}
                onChange={(event) =>
                  onDraft(setEvidence(draft, point.markPointId, event.target.value))
                }
              />
            </div>
          ))}
        </div>
      ))}
      <Button
        type="submit"
        variant="primary"
        disabled={!complete || submitting}
        loading={submitting}
        className="self-start"
      >
        Submit and reveal the marker's verdict
      </Button>
    </form>
  )
}

function RevealedOutcome({ view }: { view: SelfReviewRevealed }) {
  const groups = groupPoints<SelfReviewRevealedPoint>(view.points)
  // Only used inside the `pendingTeacher` branch below, so only computed
  // when that branch will actually render (Task 13/14 review, NIT-4).
  const pendingSummary = view.pendingTeacher ? outcomeSummary(view) : null
  return (
    <div className="flex flex-col gap-3" data-testid="self-review-outcome">
      <p className="text-body-md text-ink">{summaryLine(view)}</p>
      <ul className="flex flex-col gap-2">
        {groups.map((group) => (
          <li
            key={group.key ?? group.points[0]!.markPointId}
            className="flex flex-col gap-2 rounded-md bg-paper-sunk px-3.5 py-3"
          >
            {group.kind !== "single" ? (
              <p className="text-label text-ink-muted">{groupLabel(group)}</p>
            ) : null}
            <div className="flex flex-col gap-1.5">
              {group.points.map((point) => {
                const outcome = pointOutcome(point, view)
                const detail = outcomeDetail(point, outcome, view.evidenceRequired)
                return (
                  <div key={point.markPointId} className="flex flex-col gap-1.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-body-md text-ink">{point.pointText}</span>
                      <Chip tone={OUTCOME_TONE[outcome]}>{OUTCOME_LABEL[outcome]}</Chip>
                    </div>
                    <div className="flex flex-wrap gap-3 text-body-sm text-ink-muted">
                      <span>Marker: {point.awarded ? "awarded" : "not awarded"}</span>
                      <span>You: {point.studentSelfmark ? "earned" : "not earned"}</span>
                    </div>
                    {detail ? <p className="text-body-sm text-ink-muted">{detail}</p> : null}
                    {point.studentEvidence ? (
                      <p className="text-body-sm text-ink-faint">
                        Your reason: {point.studentEvidence}
                      </p>
                    ) : null}
                  </div>
                )
              })}
            </div>
          </li>
        ))}
      </ul>
      {pendingSummary ? (
        <p className="text-body-sm text-info">
          {pendingSummary.pending === 1
            ? "One point is waiting for a teacher."
            : `${pendingSummary.pending} points are waiting for a teacher.`}
        </p>
      ) : null}
    </div>
  )
}

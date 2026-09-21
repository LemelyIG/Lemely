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
import type { SelfReviewPending, SelfReviewRevealed } from "@/lib/selfReviewTypes"

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
  const [draft, setDraft] = useState<SelfReviewDraft>(EMPTY_DRAFT)

  if (query.isPending) return <ListSkeleton rows={2} />
  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 404) {
      return (
        <EmptyState
          compact
          heading={UNAVAILABLE_COPY}
          data-testid="self-review-unavailable"
        />
      )
    }
    return <ErrorState compact heading="We couldn't load the self-review for this question." />
  }

  const view = query.data
  if (view.state === "not_started") {
    return (
      <PendingForm
        view={view}
        draft={draft}
        onDraft={setDraft}
        submitting={submit.isPending}
        onSubmit={() =>
          submit.mutate(
            { attemptId, questionResultId, submission: toSubmission(draft, view.points) },
            {
              onError: (error) =>
                toast({
                  title:
                    error instanceof ApiError && error.status === 409
                      ? "This question has already been self-marked."
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
      {view.points.map((point) => (
        <div
          key={point.markPointId}
          className="flex flex-col gap-2 rounded-md bg-paper-sunk px-3.5 py-3"
        >
          <RadioGroup
            label={`${point.pointText} (${point.tariff} ${point.tariff === 1 ? "mark" : "marks"})`}
            value={verdictValue(draft.verdicts[point.markPointId])}
            onValueChange={(value) => onDraft(setVerdict(draft, point.markPointId, value === "earned"))}
            orientation="horizontal"
          >
            <Radio value="earned" label="I earned this" />
            <Radio value="missed" label="I did not earn this" />
          </RadioGroup>
          <Textarea
            label={
              view.evidenceRequired ? "Why? (needed to challenge the marker)" : "Why? (optional)"
            }
            rows={2}
            maxLength={2000}
            value={draft.evidence[point.markPointId] ?? ""}
            onChange={(event) => onDraft(setEvidence(draft, point.markPointId, event.target.value))}
          />
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
  const summary = outcomeSummary(view)
  return (
    <div className="flex flex-col gap-3" data-testid="self-review-outcome">
      <p className="text-body-md text-ink">{summaryLine(view)}</p>
      <ul className="flex flex-col gap-2">
        {view.points.map((point) => {
          const outcome = pointOutcome(point, view)
          const detail = outcomeDetail(point, outcome, view.evidenceRequired)
          return (
            <li
              key={point.markPointId}
              className="flex flex-col gap-1.5 rounded-md bg-paper-sunk px-3.5 py-3"
            >
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
                <p className="text-body-sm text-ink-faint">Your reason: {point.studentEvidence}</p>
              ) : null}
            </li>
          )
        })}
      </ul>
      {view.pendingTeacher ? (
        <p className="text-body-sm text-info">
          {summary.pending === 1
            ? "One point is waiting for a teacher."
            : `${summary.pending} points are waiting for a teacher.`}
        </p>
      ) : null}
    </div>
  )
}

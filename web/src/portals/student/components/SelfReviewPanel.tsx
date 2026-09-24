/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
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
import { cn } from "@/lib/utils"
import {
  EMPTY_DRAFT,
  OUTCOME_LABEL,
  UNAVAILABLE_COPY,
  draftStorageKey,
  evidenceHint,
  groupLabel,
  groupPoints,
  isComplete,
  missingEvidence,
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
 * Scheme groups (Task 13/14 review, IMP-6, R-1): `groupKey`/`groupMaxMarks`
 * mark points that share one scheme pool (an either/or run, an "any N from"
 * pool) worth `groupMaxMarks` together, never individually — both wire
 * contracts say so (`selfReviewTypes.ts`, `schemas_student_self_review.py`).
 * `groupPoints`/`groupLabel` (from `@/lib/selfReview`, unit-tested there over
 * real point arrays rather than pinned as source text here) collapse points
 * sharing a key into one card; the per-point radios still render inside it,
 * so the POST still carries a verdict for every point
 * (`SelfReviewSubmissionDTO` is unchanged). `groupLabel` states only the
 * group's total worth ("These together, worth up to 2 marks in total"), never a
 * pick-count — the wire carries no select-count field, so a count is not
 * knowable client-side; see `selfReview.ts` for why an earlier version's
 * "Any N of these" reading of `groupMaxMarks` was wrong for any group whose
 * member tariffs are not all 1.
 *
 * Re-derived Variety (pre-emit critique, was V3): every group card in both
 * states rendered as the same undifferentiated `bg-paper-sunk` box regardless
 * of what it held, even though `RevealedOutcome` already computes a per-point
 * severity via `OUTCOME_TONE`. `groupSeverity` below rolls that up per group
 * (worst outcome wins: pending > kept > changed > agreed) and the group card
 * carries it as a `border-s-2 border-s-<tone>` hairline — the same
 * inline-start accent idiom `Notifications.tsx`/`Announcements.tsx`/
 * `Overview.tsx` already use for unread/active state, not a new pattern.
 * `PendingForm`'s cards stay plain: they hold no outcome yet, so the absence
 * of the accent is itself the honest signal, not an oversight. This is the
 * component's real ceiling on Variety: it is a slot inside `QuestionRow`, not
 * a page, so Hallmark's macrostructure/nav/footer diversification doesn't
 * apply here at all — there's no nav, no footer, no theme to rotate. What
 * *is* addressable at this scope is exactly this: state-appropriate visual
 * differentiation instead of one undifferentiated grey stack.
 *
 * The draft (Task 13/14 review, SF-3) is persisted to `sessionStorage`, not
 * just component state: `QuestionRow`'s expanded slot only renders `children`
 * while `open` is true (`question-row.tsx:186`), so collapsing the row
 * unmounts this component and a plain `useState` draft would be silently
 * destroyed, taking up to 100 radio choices and 2000 characters of written
 * evidence per point with it. `sessionStorage` survives that unmount for the
 * life of the tab without needing `PaperResult` to lift and thread the state
 * through `QuestionList`/`QuestionRow` for a screen that does not otherwise
 * need to know about drafts. The clear side lives in the mutation hook's
 * option-level `onSuccess` (R-5), not here, so it still runs if this panel
 * unmounts before the POST settles.
 */

const OUTCOME_TONE: Record<PointOutcome, "ok" | "warn" | "neutral" | "info"> = {
  agreed: "neutral",
  changed: "ok",
  kept: "warn",
  pending: "info",
}

/** Lower = more attention-worthy. Mirrors the reading order a student wants:
 * an unresolved teacher review first, then a mark that didn't move their way,
 * then one that did, then plain agreement last. */
const OUTCOME_PRIORITY: Record<PointOutcome, number> = {
  pending: 0,
  kept: 1,
  changed: 2,
  agreed: 3,
}

/** Worst-outcome-wins severity for a group card. `agreed` (every point
 * matched the marker) renders with no accent at all — nothing needs
 * flagging, so the plain card is the honest state, not a missed case. */
function groupSeverity(
  points: readonly SelfReviewRevealedPoint[],
  view: Pick<SelfReviewRevealed, "pendingTeacher">,
): "ok" | "warn" | "info" | null {
  let worst: PointOutcome = "agreed"
  for (const point of points) {
    const outcome = pointOutcome(point, view)
    if (OUTCOME_PRIORITY[outcome] < OUTCOME_PRIORITY[worst]) worst = outcome
  }
  if (worst === "agreed") return null
  return OUTCOME_TONE[worst] as "ok" | "warn" | "info"
}

const GROUP_ACCENT: Record<"ok" | "warn" | "info", string> = {
  ok: "border-s-2 border-s-ok",
  warn: "border-s-2 border-s-warn",
  info: "border-s-2 border-s-info",
}

/*
 * Student-facing wording for I6's three verdicts. Deliberately NOT the teacher
 * screen's labels ("Withheld, judged absent" / "Unverifiable, could not
 * confirm"): that is institutional hedging to a student mid-revision, and this
 * copy says the same thing while implying what to do differently. The two
 * vocabularies are intended -- see the 2026-09-24 production-readiness spec.
 */
const STUDENT_VERDICT_LABEL: Record<"awarded" | "withheld" | "unverifiable", string> = {
  awarded: "Marked correct",
  withheld: "We did not see this step in your answer",
  unverifiable: "The marker credited this, but we could not confirm your value",
}

function verdictValue(earned: boolean | undefined): string | undefined {
  if (earned === undefined) return undefined
  return earned ? "earned" : "missed"
}

/** Reads a saved draft back for the initial `useState` value. Wrapped: a
 * private window, cleared site data, or storage genuinely disabled must
 * still render the ordinary empty form, not throw. `clearDraft` (the write
 * side's counterpart) lives in `@/lib/selfReview`, called from the mutation
 * hook's option-level `onSuccess` rather than here — see that file for why
 * (Task 13/14 re-review, R-5). */
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
  // `isLoadingError` (as opposed to `isError`) is true only when the query
  // has never held data: `isLoadingError = isError && !hasData`
  // (@tanstack/query-core's own `queryObserver.js`), so a background refetch
  // that fails — the query still holds the last good payload — falls
  // through to render that payload instead. A plain `isError` check here
  // replaced a completed, filled-in form with this error screen the moment
  // the new IMP-1 `onError` invalidation's own refetch failed offline (Task
  // 13/14 re-review, R-2): the student's work vanished behind "We couldn't
  // load the self-review" with a Try-again button that could only refetch,
  // never resubmit. `isLoadingError` keeps the stale-but-real cached view on
  // screen instead, which is exactly what a student mid-form needs while
  // offline.
  if (query.isLoadingError) {
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
  const [attemptedSubmit, setAttemptedSubmit] = useState(false)
  const complete = isComplete(draft, view.points)
  const missing = missingEvidence(draft, view.points, view.evidenceRequired)
  const canSubmit = complete && missing.length === 0
  const groups = groupPoints<SelfReviewPendingPoint>(view.points)
  return (
    <form
      className="flex flex-col gap-4"
      data-testid="self-review-form"
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit && !submitting) {
          onSubmit()
          return
        }
        setAttemptedSubmit(true)
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
            <p className="text-label text-ink">{groupLabel(group)}</p>
          ) : null}
          {group.points.map((point) => (
            <div key={point.markPointId} className="flex flex-col gap-2">
              <RadioGroup
                label={
                  group.kind === "single"
                    ? `${point.pointText} (${groupLabel(group)})`
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
                hint="Up to 2000 characters"
                error={
                  attemptedSubmit && missing.includes(point.markPointId)
                    ? "Say what in your answer earns this, or the marker's mark stands."
                    : undefined
                }
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
        {groups.map((group) => {
          const severity = groupSeverity(group.points, view)
          return (
            <li
              key={group.key ?? group.points[0]!.markPointId}
              className={cn(
                "flex flex-col gap-2 rounded-md bg-paper-sunk px-3.5 py-3",
                severity ? GROUP_ACCENT[severity] : null,
              )}
            >
              {group.kind !== "single" ? (
                <p className="text-label text-ink">{groupLabel(group)}</p>
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
                      {point.verdict ? (
                        <Chip tone="neutral">{STUDENT_VERDICT_LABEL[point.verdict]}</Chip>
                      ) : null}
                      {point.ecfApplied ? (
                        <Chip tone="info">Carried forward, so one earlier slip did not cost you twice</Chip>
                      ) : null}
                      {point.evidenceSpan ? (
                        <p className="text-body-sm text-ink-muted m-0 whitespace-pre-wrap">
                          "{point.evidenceSpan}"
                        </p>
                      ) : null}
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
          )
        })}
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

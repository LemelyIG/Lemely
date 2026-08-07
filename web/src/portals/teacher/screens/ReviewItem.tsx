import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { Flag } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ErrorState } from "@/components/ui/state-views"
import { initialsOf, relativeTime } from "@/lib/utils"
import { Avatar } from "../components/Avatar"
import {
  useDismissReviewItem,
  useResolveReviewItem,
  useReviewItem,
  useReviewQueue,
} from "@/lib/hooks/useTeacherApi"
import type { ReviewBreakdown, ReviewItemDetail } from "@/lib/teacherTypes"
import { confidenceTone, isIntegrityReason, paperIdentityLabel, reasonLabel } from "./Review"

/*
 * Review item — remark (T-08). `GET /teacher/review/{itemId}`
 * (`useReviewItem()`) is the single fetch every panel below projects
 * directly.
 *
 * **Route, not a pane beside the queue** (`/teacher/review/:itemId`). T-07's
 * filter querystring (`class_id`/`reason`/`min_age_hours`) is carried
 * through in the URL rather than component state/context, which is what
 * makes both halves of the "next item" workflow honest: (1) "next" walks
 * `useReviewQueue()` fetched with the *same* filters the teacher was
 * triaging under, not the whole unfiltered queue, so a batch stays a batch;
 * (2) the item is independently deep-linkable/bookmarkable/back-button-able
 * like every other drill-down route in this portal (T-03→T-05, T-06→T-05),
 * rather than a mode of the list that a page refresh or a shared link loses.
 * The filtered queue fetch usually costs nothing extra — same query key as
 * `Review.tsx` just used to get here, so react-query serves it from cache.
 *
 * **D3.14 §1 drives the whole evidence layout.** The spec asks for "the
 * student's actual scan crop, side by side with the mark scheme extract" —
 * neither is persisted anywhere in this product (`ReviewItemDetailDTO`'s own
 * docstring). What's rendered instead, explicitly labelled as such, with a
 * banner stating the scan/scheme extract don't exist rather than a
 * placeholder image or skeleton frame standing in for a missing asset:
 *  - `studentAnswer` -> "Lemely's transcription of the student's answer —
 *    not the scan."
 *  - `expectedAnswer` -> "Expected answer" (the mark scheme's target, not
 *    its full prose).
 *  - `matchedPointIds` -> rendered as bare identifier chips, labelled
 *    "identifiers only — the scheme's own wording isn't stored" — never
 *    reconstructed into scheme-sounding prose (UI-spec §1.4: never invent
 *    precision the data doesn't support).
 *
 * **Integrity items (`plagiarism_flag`/`ai_detection_flag`) get dismiss
 * only on this screen; accept/adjust-marks controls render for every other
 * reason instead, never both on the same item.** The backend's `resolve`
 * endpoint has no reason restriction, so a teacher *could* also
 * accept/override an integrity-flagged item's marks — but that would be a
 * second, parallel way to close the same row with different wording and
 * different consequences (dismiss touches no `QuestionResult` at all;
 * resolve can rewrite one), which is more confusing than useful. Marks on
 * the *same question* still get their own dedicated `low_confidence` row
 * when relevant (`AttemptRepository.persist_correction` writes one row per
 * reason) — this judgment call only decides what a single flagged *row*
 * offers, not what's reachable for the question overall. The integrity
 * panel itself is deliberately amber/neutral, never red, with an icon (not
 * color alone) — spec §1.4: "flags are signals, not verdicts", never
 * phrased as a conclusion about the student — and dismissing states plainly
 * that no record reaches the student, matching `ReviewService.dismiss`'s
 * actual behaviour (it never touches `QuestionResult`).
 *
 * **The "note to the student" control only appears in the adjust-marks
 * form**, because it's the only path where it does anything real:
 * `ResolveReviewRequestDTO.note` becomes `QuestionResult.teacherNote` only
 * when `overrideMarks` is supplied; on the accept-as-is path the same field
 * is stored as an *internal* resolution note instead (see
 * `ReviewService.resolve`'s docstring) — the two textareas are labelled
 * accordingly, never the same generic "note" for both. **Neither path
 * claims the student is notified**: `resolve()` never writes to a
 * notification table and no frontend surface renders `teacherNote` on the
 * student side yet (verified — no symbol named `teacherAwardedMarks` or
 * `isOverridden` exists anywhere under `portals/student/`), so despite the
 * UI spec's "notifies them", there is no real delivery path today. The copy
 * here says only what actually happens (saved on the corrected result),
 * never that the student is pinged — a gap worth flagging in the phase
 * report, not one this frontend-only chunk can close.
 *
 * **Keyboard shortcuts** (`A` accept-as-is, `N` next item, `Esc` back to
 * queue) are a thin layer over the same handlers the visible buttons call —
 * never the only way to do any of these — and are inert whenever focus sits
 * in an input/textarea/select or a modifier key is held, so they can't
 * fight normal typing or a screen reader's own key handling. A visible
 * `<kbd>` hint strip makes them discoverable rather than hidden knowledge.
 * `A` is wired via a ref callback (`registerAccept`) so the parent's single
 * keydown listener can trigger the accept handler that actually lives in
 * `ResolveControls` (it owns the note text the accept action sends) without
 * lifting that form's whole state up.
 */

function AwardedMarks({ detail }: { detail: ReviewItemDetail }) {
  return (
    <div className="font-serif text-[30px] leading-none">
      {detail.aiAwardedMarks ?? "—"}
      <span className="text-[16px] text-t2">/{detail.maximumMarks ?? "—"}</span>
    </div>
  )
}

function DismissForm({ itemId, onDone }: { itemId: string; onDone: () => void }) {
  const dismiss = useDismissReviewItem(itemId)
  const [note, setNote] = useState("")

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        dismiss.mutate({ note: note.trim() || undefined }, { onSuccess: onDone })
      }}
      className="flex flex-col gap-2.5"
    >
      <label className="flex flex-col gap-1.5 text-[12px] text-t2">
        Internal note (optional — visible only to you, never the student)
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          className="border border-border bg-surface rounded-md px-2.5 py-2 text-[12.5px] text-t1 resize-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        />
      </label>
      <div>
        <Button type="submit" variant="ink" disabled={dismiss.isPending}>
          {dismiss.isPending ? "Dismissing…" : "Dismiss flag"}
        </Button>
      </div>
      {dismiss.isError ? (
        <div role="alert" className="text-[12.5px] text-err">
          Couldn't dismiss: {dismiss.error.message}
        </div>
      ) : null}
    </form>
  )
}

function ResolveControls({
  detail,
  onDone,
  registerAccept,
}: {
  detail: ReviewItemDetail
  onDone: () => void
  registerAccept: (fn: (() => void) | null) => void
}) {
  const resolve = useResolveReviewItem(detail.itemId)
  const [mode, setMode] = useState<"accept" | "adjust">("accept")
  const [acceptNote, setAcceptNote] = useState("")
  const [overrideMarks, setOverrideMarks] = useState(
    detail.aiAwardedMarks != null ? String(detail.aiAwardedMarks) : "",
  )
  const [methodMarks, setMethodMarks] = useState("")
  const [accuracyMarks, setAccuracyMarks] = useState("")
  const [otherMarks, setOtherMarks] = useState("")
  const [breakdownNotes, setBreakdownNotes] = useState("")
  const [studentNote, setStudentNote] = useState("")
  const [validationError, setValidationError] = useState<string | null>(null)

  const canAdjust = detail.questionResultId != null

  const handleAccept = useCallback(() => {
    resolve.mutate({ note: acceptNote.trim() || undefined }, { onSuccess: onDone })
  }, [resolve, acceptNote, onDone])

  useEffect(() => {
    registerAccept(mode === "accept" && !resolve.isPending ? handleAccept : null)
    return () => registerAccept(null)
  }, [registerAccept, handleAccept, mode, resolve.isPending])

  function handleSaveCorrection(e: FormEvent) {
    e.preventDefault()
    const marks = Number(overrideMarks)
    const max = detail.maximumMarks ?? 0
    if (overrideMarks.trim() === "" || !Number.isFinite(marks) || marks < 0 || marks > max) {
      setValidationError(`Enter a whole number of marks between 0 and ${max}.`)
      return
    }
    setValidationError(null)
    const breakdown: ReviewBreakdown = {
      methodMarks: methodMarks.trim() ? Number(methodMarks) : null,
      accuracyMarks: accuracyMarks.trim() ? Number(accuracyMarks) : null,
      otherMarks: otherMarks.trim() ? Number(otherMarks) : null,
      notes: breakdownNotes.trim() || null,
    }
    const hasBreakdown = Object.values(breakdown).some((v) => v !== null)
    resolve.mutate(
      {
        overrideMarks: Math.round(marks),
        breakdown: hasBreakdown ? breakdown : undefined,
        note: studentNote.trim() || undefined,
      },
      { onSuccess: onDone },
    )
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="font-serif text-[20px]">Your decision</div>
      <div className="bg-surface border border-border rounded-[14px] p-[18px] flex flex-col gap-4">
        {mode === "accept" ? (
          <>
            <label className="flex flex-col gap-1.5 text-[12.5px] text-t2">
              Internal note (optional — visible only to you and other teachers, not the student)
              <textarea
                value={acceptNote}
                onChange={(e) => setAcceptNote(e.target.value)}
                rows={2}
                className="border border-border bg-surface rounded-md px-2.5 py-2 text-[12.5px] text-t1 resize-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              />
            </label>
            <div className="flex items-center gap-2.5 flex-wrap">
              <Button type="button" variant="ink" disabled={resolve.isPending} onClick={handleAccept}>
                {resolve.isPending ? "Saving…" : "Accept as-is"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={!canAdjust}
                title={canAdjust ? undefined : "No mark data on this item to adjust"}
                onClick={() => setMode("adjust")}
              >
                Adjust marks instead
              </Button>
            </div>
          </>
        ) : (
          <form onSubmit={handleSaveCorrection} className="flex flex-col gap-3">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <label className="flex flex-col gap-1.5 text-[12px] text-t2">
                Marks to award
                <input
                  type="number"
                  min={0}
                  max={detail.maximumMarks ?? undefined}
                  value={overrideMarks}
                  onChange={(e) => setOverrideMarks(e.target.value)}
                  className="border border-border bg-surface rounded-md px-2.5 py-1.5 text-[13px] text-t1 font-mono focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                />
              </label>
              <label className="flex flex-col gap-1.5 text-[12px] text-t2">
                Method
                <input
                  type="number"
                  min={0}
                  value={methodMarks}
                  onChange={(e) => setMethodMarks(e.target.value)}
                  className="border border-border bg-surface rounded-md px-2.5 py-1.5 text-[13px] text-t1 font-mono focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                />
              </label>
              <label className="flex flex-col gap-1.5 text-[12px] text-t2">
                Accuracy
                <input
                  type="number"
                  min={0}
                  value={accuracyMarks}
                  onChange={(e) => setAccuracyMarks(e.target.value)}
                  className="border border-border bg-surface rounded-md px-2.5 py-1.5 text-[13px] text-t1 font-mono focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                />
              </label>
              <label className="flex flex-col gap-1.5 text-[12px] text-t2">
                Other
                <input
                  type="number"
                  min={0}
                  value={otherMarks}
                  onChange={(e) => setOtherMarks(e.target.value)}
                  className="border border-border bg-surface rounded-md px-2.5 py-1.5 text-[13px] text-t1 font-mono focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                />
              </label>
            </div>
            <label className="flex flex-col gap-1.5 text-[12px] text-t2">
              Breakdown notes (internal — how you split the marks)
              <textarea
                value={breakdownNotes}
                onChange={(e) => setBreakdownNotes(e.target.value)}
                rows={2}
                className="border border-border bg-surface rounded-md px-2.5 py-2 text-[12.5px] text-t1 resize-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-[12px] text-t2">
              Note to the student — saved on their corrected result as the reason for the change
              <textarea
                value={studentNote}
                onChange={(e) => setStudentNote(e.target.value)}
                rows={2}
                className="border border-border bg-surface rounded-md px-2.5 py-2 text-[12.5px] text-t1 resize-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              />
            </label>
            {validationError ? (
              <div role="alert" className="text-[12.5px] text-err">
                {validationError}
              </div>
            ) : null}
            <div className="flex items-center gap-2.5 flex-wrap">
              <Button type="submit" variant="ink" disabled={resolve.isPending}>
                {resolve.isPending ? "Saving…" : "Save correction"}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setMode("accept")}>
                Cancel
              </Button>
            </div>
          </form>
        )}
        {resolve.isError ? (
          <div role="alert" className="text-[12.5px] text-err">
            Couldn't save: {resolve.error.message}
          </div>
        ) : null}
      </div>
    </section>
  )
}

export function ReviewItem() {
  const { itemId } = useParams<{ itemId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const filterQs = searchParams.toString()

  const classId = searchParams.get("class_id") ?? undefined
  const filterReason = searchParams.get("reason") ?? undefined
  const minAgeHoursRaw = searchParams.get("min_age_hours")
  const minAgeHours = minAgeHoursRaw ? Number(minAgeHoursRaw) : undefined

  const detailQuery = useReviewItem(itemId)
  const queueQuery = useReviewQueue({ classId, reason: filterReason, minAgeHours })

  const acceptHandlerRef = useRef<(() => void) | null>(null)
  const registerAccept = useCallback((fn: (() => void) | null) => {
    acceptHandlerRef.current = fn
  }, [])

  const queueIds = queueQuery.data?.items.map((i) => i.itemId) ?? []
  const currentIndex = itemId ? queueIds.indexOf(itemId) : -1
  const nextItemId = currentIndex >= 0 ? queueIds[currentIndex + 1] : undefined

  const goToQueue = useCallback(() => {
    navigate(`/teacher/review${filterQs ? `?${filterQs}` : ""}`)
  }, [navigate, filterQs])

  const goNext = useCallback(() => {
    if (nextItemId) {
      navigate(`/teacher/review/${nextItemId}${filterQs ? `?${filterQs}` : ""}`)
    } else {
      goToQueue()
    }
  }, [navigate, nextItemId, filterQs, goToQueue])

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === "Escape") {
        e.preventDefault()
        goToQueue()
      } else if (e.key === "n" || e.key === "N") {
        e.preventDefault()
        goNext()
      } else if (e.key === "a" || e.key === "A") {
        if (acceptHandlerRef.current) {
          e.preventDefault()
          acceptHandlerRef.current()
        }
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [goToQueue, goNext])

  if (detailQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Review item</h1>
        <div role="status" className="text-[13.5px] text-t2">
          Loading review item…
        </div>
      </div>
    )
  }

  if (detailQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Review item</h1>
        <ErrorState
          heading="Couldn't load this review item"
          body={detailQuery.error.message}
          action={{ label: "Retry", onClick: () => detailQuery.refetch() }}
          secondaryAction={{ label: "Back to queue", onClick: goToQueue }}
        />
      </div>
    )
  }

  const detail = detailQuery.data
  const integrity = isIntegrityReason(detail.reason)

  return (
    <div className="lm-screen flex flex-col gap-6 min-w-0">
      <div className="flex flex-col gap-1">
        <button
          type="button"
          onClick={goToQueue}
          className="text-[12px] text-t3 hover:text-t1 w-fit bg-transparent border-0 p-0 cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← Back to queue
        </button>
        <div className="flex items-start gap-3.5 flex-wrap gap-y-2 mt-1">
          <Avatar
            initials={initialsOf(detail.studentDisplayName)}
            tone="accent"
            className="w-9 h-9 text-[13px] flex-none"
          />
          <div className="min-w-0">
            <h1 className="font-serif text-[26px] leading-[1.15] text-pretty">
              {detail.studentDisplayName}
            </h1>
            <div className="text-[12.5px] text-t2 mt-0.5">
              {detail.className} · {paperIdentityLabel(detail)}
              {detail.questionId ? ` · Q${detail.questionId}` : ""}
            </div>
          </div>
          <div className="flex-1" />
          <div className="flex items-center gap-2 flex-none">
            {detail.status !== "open" ? (
              <Chip tone={detail.status === "dismissed" ? "neutral" : "ok"}>
                {detail.status === "dismissed" ? "Dismissed" : "Resolved"}
              </Chip>
            ) : null}
            <Chip tone={integrity ? "warn" : "neutral"}>{reasonLabel(detail.reason)}</Chip>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 flex-wrap border-y border-border py-2.5">
        <div className="flex items-center gap-4 flex-wrap text-[11px] text-t3 font-mono">
          <span className="flex items-center gap-1.5">
            <kbd className="px-1.5 py-0.5 rounded border border-border bg-surface-2 text-t2">A</kbd>
            accept as-is
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="px-1.5 py-0.5 rounded border border-border bg-surface-2 text-t2">N</kbd>
            next item
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="px-1.5 py-0.5 rounded border border-border bg-surface-2 text-t2">Esc</kbd>
            back to queue
          </span>
        </div>
        <Button type="button" variant="secondary" size="sm" onClick={goNext}>
          {nextItemId ? "Next item →" : "Back to queue →"}
        </Button>
      </div>

      {/* Evidence: honest substitutes for the scan crop / mark-scheme extract (D3.14 §1) */}
      <section className="flex flex-col gap-3">
        <div className="font-serif text-[20px]">What Lemely saw</div>
        <div className="text-[12.5px] text-t2 bg-surface-2 border border-border rounded-[10px] px-3.5 py-3 text-pretty">
          The original scan image and the mark scheme's own wording aren't stored anywhere in
          this product — what's below is the closest honest record: Lemely's own transcription
          of the student's answer, and the identifiers of the mark-scheme points it matched.
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="bg-surface border border-border rounded-[14px] p-[18px] flex flex-col gap-2 min-w-0">
            <div className="font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
              Lemely's transcription of the student's answer — not the scan
            </div>
            {detail.studentAnswer ? (
              <p className="text-[13.5px] leading-[1.55] text-pretty whitespace-pre-wrap m-0">
                {detail.studentAnswer}
              </p>
            ) : (
              <p className="text-[13px] text-t3 m-0">No transcription recorded for this question.</p>
            )}
          </div>
          <div className="bg-surface border border-border rounded-[14px] p-[18px] flex flex-col gap-3 min-w-0">
            <div>
              <div className="font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                Expected answer
              </div>
              {detail.expectedAnswer ? (
                <p className="text-[13.5px] leading-[1.55] text-pretty whitespace-pre-wrap mt-1 mb-0">
                  {detail.expectedAnswer}
                </p>
              ) : (
                <p className="text-[13px] text-t3 mt-1 mb-0">No expected answer recorded.</p>
              )}
            </div>
            <div>
              <div className="font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                Matched mark-scheme points — identifiers only, the scheme's own wording isn't
                stored
              </div>
              {detail.matchedPointIds.length > 0 ? (
                <div className="flex flex-wrap gap-1.5 mt-1.5">
                  {detail.matchedPointIds.map((id) => (
                    <Chip key={id} tone="neutral">
                      {id}
                    </Chip>
                  ))}
                </div>
              ) : (
                <p className="text-[13px] text-t3 mt-1 mb-0">No points matched.</p>
              )}
            </div>
          </div>
        </div>
        {detail.topic ? <div className="text-[12px] text-t3">Topic: {detail.topic}</div> : null}
      </section>

      {/* What Lemely awarded, and why this needs a look */}
      <section className="flex flex-col gap-3">
        <div className="font-serif text-[20px]">What Lemely awarded</div>
        <div className="bg-surface border border-border rounded-[14px] p-[18px] flex flex-col gap-4">
          <div className="flex items-center gap-4 flex-wrap">
            <AwardedMarks detail={detail} />
            {detail.confidenceScore != null ? (
              <Chip tone={confidenceTone(detail.confidenceScore)}>
                {Math.round(detail.confidenceScore * 100)}% confidence
              </Chip>
            ) : (
              <Chip tone="neutral">Confidence unavailable</Chip>
            )}
          </div>
          {detail.reviewReason ? (
            <div className="border-t border-border pt-3">
              <div className="font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                Why this needs review
              </div>
              <p className="text-[13px] text-t2 leading-[1.5] mt-1.5 mb-0 text-pretty">
                {detail.reviewReason}
              </p>
            </div>
          ) : null}
          {detail.feedback ? (
            <div className="border-t border-border pt-3">
              <div className="font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                Lemely's feedback
              </div>
              <p className="text-[13px] text-t2 leading-[1.5] mt-1.5 mb-0 text-pretty">
                {detail.feedback}
              </p>
            </div>
          ) : null}
        </div>
      </section>

      {/* Integrity flag: distinct, non-inflammatory, dismiss-only on this item */}
      {integrity ? (
        <section className="border border-warn rounded-[14px] p-[18px] bg-warn-bg flex flex-col gap-3">
          <div className="flex items-center gap-2.5">
            <Flag weight="fill" className="w-[18px] h-[18px] text-warn flex-none" aria-hidden />
            <div className="font-medium text-[14px] text-t1">Flagged: {reasonLabel(detail.reason)}</div>
          </div>
          <p className="text-[12.5px] text-t2 leading-[1.5] m-0 text-pretty">
            This is a signal for you to look at — not a conclusion about the student. If you
            dismiss it, nothing about this flag reaches the student: dismissing never touches
            their mark or their result.
          </p>
          {detail.status === "open" ? (
            <DismissForm itemId={detail.itemId} onDone={goNext} />
          ) : (
            <div className="text-[12px] text-t3">
              {detail.status === "dismissed" ? "Dismissed" : "Resolved"}
              {detail.resolutionNote ? ` — "${detail.resolutionNote}"` : "."}
            </div>
          )}
        </section>
      ) : null}

      {/* Accept / adjust marks — non-integrity items only, open only */}
      {!integrity && detail.status === "open" ? (
        <ResolveControls detail={detail} onDone={goNext} registerAccept={registerAccept} />
      ) : null}

      {!integrity && detail.status !== "open" && detail.resolutionNote ? (
        <div className="text-[12.5px] text-t2">Resolution note: "{detail.resolutionNote}"</div>
      ) : null}

      {detail.isOverridden ? (
        <section className="flex flex-col gap-3">
          <div className="font-serif text-[20px]">Teacher correction on record</div>
          <div className="bg-surface border border-border rounded-[14px] p-[18px] flex flex-col gap-2">
            <div className="font-serif text-[24px]">
              {detail.teacherAwardedMarks}
              <span className="text-[14px] text-t2">/{detail.maximumMarks ?? "—"}</span>
            </div>
            {detail.teacherNote ? (
              <p className="text-[13px] text-t2 m-0 text-pretty">"{detail.teacherNote}"</p>
            ) : null}
            {detail.overriddenAt ? (
              <div className="text-[11.5px] text-t3">{relativeTime(detail.overriddenAt)}</div>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  )
}

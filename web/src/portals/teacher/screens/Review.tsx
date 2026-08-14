/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useRef, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Chip } from "@/components/ui/chip"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { relativeTime } from "@/lib/utils"
import { confidenceTierFor } from "@/lib/markingConfidence"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import {
  teacherLoadFailureMessage,
  teacherMutationFailureMessage,
} from "@/lib/teacherOutcome"
import { Avatar } from "@/components/ui/avatar"
import { useBulkApproveReview, useReviewQueue, useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import type { BulkApproveResponse, ReviewQueueItem } from "@/lib/teacherTypes"

/*
 * Review queue (T-07). `GET /teacher/review?class_id=&reason=&min_age_hours=`
 * (`useReviewQueue()`) — replaces the old mock-modeled `Review.tsx`, which was
 * wired to the P2 grading console's paper-level `GET /grading/queue`
 * (`useGradingQueue`, now deleted — see `useTeacherApi.ts`'s module doc). That
 * screen answered a different question ("which papers are flagged"); this one
 * answers T-07's real one ("which individual marked *questions* need a
 * teacher's eyes, and why"), one row per open `review_queue` row (P3.4). The
 * P2 grading console itself is untouched and still reachable at
 * `/teacher/grading`.
 *
 * **All three filters (class/reason/age) are real server-side query
 * params**, kept in the URL (`useSearchParams`) rather than component state,
 * for two reasons: (1) never re-filter an unfiltered fetch client-side, and
 * (2) the exact same querystring is threaded through to T-08 so its "next
 * item" action walks the same filtered batch the teacher opened, and "back
 * to queue" restores the filters instead of silently resetting them.
 *
 * **`manual` is deliberately excluded from the reason filter.** Nothing in
 * the current pipeline (`AttemptRepository.persist_correction`, the only
 * place `ReviewQueueItem` rows are created) ever writes a `manual`-reason
 * row — every row is `low_confidence`, `plagiarism_flag`, or
 * `ai_detection_flag`. Offering a filter option that can never match a real
 * row today would imply data this build doesn't have — the same reasoning
 * that used to keep `below_target` out of `AtRiskList.tsx`'s reason filter
 * before P4.3/D4.5 wired up a real target grade there; `manual` has no such
 * wiring in this codebase, so it stays excluded.
 * **Separately, the spec's fourth T-07 reason category — "student disputed
 * the transcription" — has no backing `ReviewReason` value or creation path
 * anywhere in this codebase.** `manual` is the closest enum member but is a
 * generic, currently-unused catch-all, not specifically a dispute flow;
 * labelling it "student disputed" would be inventing a meaning the backend
 * doesn't assert. Reported as a new spec-vs-backend gap in the phase report,
 * not fixed here (a dispute flow is a real feature, out of this chunk's
 * scope — no backend change was authorized).
 *
 * **The list renders in the order the server returns it (oldest-created
 * first = longest-waiting = highest priority) and is never re-sorted
 * client-side** — `ReviewService.list_queue` already orders by
 * `created_at` ascending; that IS the "prioritised list" the spec asks for.
 *
 * **Bulk-approve is skip-and-report** (`BulkApproveResponseDTO`): a success
 * response can still contain `skipped` entries (another teacher already
 * closed the item, it left scope, etc.) and the UI must show that honestly,
 * never claim blanket success. The skip banner resolves each skipped id back
 * to a readable student/question label using a snapshot of the queue rows
 * taken at the moment bulk-approve was triggered (`snapshotRef`) — the query
 * itself gets invalidated and refetched on success, so by the time the
 * banner renders the just-approved/skipped rows may already be gone from
 * `queueQuery.data`.
 */

export const REASON_LABEL: Record<string, string> = {
  low_confidence: "Low confidence",
  plagiarism_flag: "Possible mark-scheme copying",
  ai_detection_flag: "Possible AI-written answer",
  manual: "Manually flagged",
}

export function reasonLabel(reason: string): string {
  return REASON_LABEL[reason] ?? reason
}

const INTEGRITY_REASONS = new Set(["plagiarism_flag", "ai_detection_flag"])

export function isIntegrityReason(reason: string): boolean {
  return INTEGRITY_REASONS.has(reason)
}

/** Honest paper-identity line. A review item can originate from a quiz
 * question (P3.5's low-confidence quiz marking path also queues review
 * items) whose `Attempt` carries no subject/paper/session fields at all —
 * render "Quiz question" rather than a blank or half-filled identity line. */
export function paperIdentityLabel(item: {
  subjectCode: string | null
  paperNumber: number | null
  paperVariant: number | null
  sessionMonth: string | null
  sessionYear: number | null
}): string {
  if (!item.subjectCode) return "Quiz question"
  const parts = [item.subjectCode]
  if (item.paperNumber != null) {
    parts.push(`Paper ${item.paperNumber}${item.paperVariant != null ? `/${item.paperVariant}` : ""}`)
  }
  if (item.sessionMonth && item.sessionYear) {
    parts.push(`${item.sessionMonth} ${item.sessionYear}`)
  }
  return parts.join(" · ")
}

/**
 * Colour-coded confidence tone. The number itself is always rendered too
 * (QUALITY-BAR: colour is never the sole carrier of meaning), so this only
 * picks which semantic token tints the chip.
 *
 * **P4.5: this bucketed at 0.8, on the one screen where that is worst.** The
 * review queue exists *because* a mark scored below
 * `REVIEW_CONFIDENCE_THRESHOLD` (0.90) — that is what put it here. Painting
 * anything at or above 0.8 with the `ok` token meant a mark at 0.85 arrived in
 * the queue as not-confident and was then shown to the teacher in the same
 * green the product uses for "we are sure about this one". A teacher scanning
 * the queue for what actually needs their judgement was being pointed away
 * from items the marker had already said it was unsure about.
 *
 * This is D4.2's finding a second time. There it was the student's paper
 * result at 0.85 against the backend's 0.90; `lib/markingConfidence.ts` was
 * built to be the single owner of this decision precisely so it could not
 * happen again, and this file is now a caller rather than a second authority.
 *
 * **It also drops from three tones to two, and that is the point rather than
 * a casualty.** The old third band split "uncertain" again at 0.5, and there
 * is no such number anywhere in the product: the backend has exactly one
 * confidence threshold, so any second boundary is a frontend invention, which
 * is the defect class this whole module exists to close. Two tones is what the
 * data actually supports. Nothing is lost to the reader, because the score
 * itself is always printed beside the chip: a teacher can still tell 30% from
 * 85%, they simply are not told that the product considers one of them a
 * different *kind* of doubt when it has no basis for saying so.
 *
 * `null` stays its own case: a queue item with no score at all, which the
 * integrity checks produce, is genuinely not the same as a low score.
 */
export function confidenceTone(score: number | null): "ok" | "warn" {
  if (score == null) return "warn"
  return confidenceTierFor({ confidence: score }) === "confident" ? "ok" : "warn"
}

const REASON_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All reasons" },
  { value: "low_confidence", label: "Low confidence" },
  { value: "plagiarism_flag", label: "Possible mark-scheme copying" },
  { value: "ai_detection_flag", label: "Possible AI-written answer" },
]

const AGE_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Any age" },
  { value: "6", label: "6+ hours" },
  { value: "24", label: "24+ hours" },
  { value: "72", label: "3+ days" },
  { value: "168", label: "7+ days" },
]

const SKIP_REASON_LABEL: Record<string, string> = {
  not_found: "no longer exists",
  forbidden: "outside your classes",
  already_closed: "already resolved or dismissed",
}

function questionLabel(item: ReviewQueueItem): string {
  return item.questionId ? `Q${item.questionId}` : "this question"
}

export function Review() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const classId = searchParams.get("class_id") ?? ""
  const reason = searchParams.get("reason") ?? ""
  const minAgeHours = searchParams.get("min_age_hours") ?? ""

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkResult, setBulkResult] = useState<BulkApproveResponse | null>(null)
  const snapshotRef = useRef<ReviewQueueItem[]>([])

  const classesQuery = useTeacherClasses()
  const queueQuery = useReviewQueue({
    classId: classId || undefined,
    reason: reason || undefined,
    minAgeHours: minAgeHours ? Number(minAgeHours) : undefined,
  })
  const bulkApprove = useBulkApproveReview()

  // A selection made under one filter combination shouldn't silently carry
  // over (and get bulk-approved) once the visible set changes underneath it.
  useEffect(() => {
    setSelected(new Set())
  }, [classId, reason, minAgeHours])

  function updateFilter(key: string, value: string) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true },
    )
  }

  function toggleSelected(itemId: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  // Integrity-flagged rows are excluded from bulk-select entirely — T-08
  // deliberately gives them a separate, careful "signal, not verdict"
  // treatment with a distinct dismiss action; the backend's bulk-approve has
  // no reason restriction (`ReviewService.bulk_approve` closes any open
  // item), so without this an integrity flag could be silently closed via
  // an anonymous multi-select, bypassing that framing entirely. Found during
  // this chunk's own verification pass, not spec-mandated — a defensible
  // product judgment call, not a backend contract.
  function selectableOf(items: ReviewQueueItem[]): ReviewQueueItem[] {
    return items.filter((i) => !isIntegrityReason(i.reason))
  }

  function toggleSelectAll(items: ReviewQueueItem[]) {
    const eligible = selectableOf(items)
    setSelected((prev) =>
      eligible.length > 0 && eligible.every((i) => prev.has(i.itemId))
        ? new Set()
        : new Set(eligible.map((i) => i.itemId)),
    )
  }

  function handleBulkApprove(items: ReviewQueueItem[]) {
    snapshotRef.current = items
    bulkApprove.mutate([...selected], {
      onSuccess: (data) => {
        setBulkResult(data)
        setSelected(new Set())
      },
    })
  }

  if (queueQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Review queue</h1>
        <PageHeaderSkeleton />
        <ListSkeleton rows={6} avatar />
      </div>
    )
  }

  if (queueQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Review queue</h1>
        <ErrorState
          heading="Couldn't load the review queue"
          body={teacherLoadFailureMessage(queueQuery.error)}
          action={{ label: "Retry", onClick: () => queueQuery.refetch() }}
        />
      </div>
    )
  }

  const items = queueQuery.data.items
  const filterQsString = searchParams.toString()
  const filtersActive = classId !== "" || reason !== "" || minAgeHours !== ""
  const selectableItems = selectableOf(items)
  const allSelected = selectableItems.length > 0 && selectableItems.every((i) => selected.has(i.itemId))

  return (
    <div className="lm-screen flex flex-col gap-6 min-w-0">
      <div className="flex flex-col gap-1">
        <div className="text-eyebrow text-ink-faint">
          The teacher's core recurring task
        </div>
        <h1 className="text-display-md mt-1">Review queue</h1>
        <p className="text-body-md text-ink-muted mt-1 max-w-[560px] text-pretty">
          Low-confidence marks and integrity flags land here, oldest first. Bulk-approve the
          trivially fine ones. Open anything that needs a real look.
        </p>
      </div>

      <div className="flex items-end gap-4 flex-wrap">
        <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted">
          Class
          <select
            value={classId}
            onChange={(e) => updateFilter("class_id", e.target.value)}
            className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-body-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring min-w-[170px]"
          >
            <option value="">All classes</option>
            {(classesQuery.data?.classes ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted">
          Reason
          <select
            value={reason}
            onChange={(e) => updateFilter("reason", e.target.value)}
            className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-body-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            {REASON_FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted">
          Waiting at least
          <select
            value={minAgeHours}
            onChange={(e) => updateFilter("min_age_hours", e.target.value)}
            className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-body-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            {AGE_FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {items.length === 0 ? (
        <EmptyState
          heading={filtersActive ? "No matches for these filters" : "Nothing waiting for review"}
          body={
            filtersActive
              ? "No open review item matches the current class/reason/age filters."
              : "Every mark is either confident or already resolved. Nothing needs your eyes right now."
          }
          action={
            filtersActive
              ? { label: "Clear filters", onClick: () => setSearchParams({}, { replace: true }) }
              : undefined
          }
        />
      ) : (
        <>
          <div className="flex items-center gap-3 flex-wrap">
            <Checkbox
              checked={allSelected}
              disabled={selectableItems.length === 0}
              onChange={() => toggleSelectAll(items)}
              aria-label={allSelected ? "Deselect all selectable items" : "Select all selectable items"}
              label={selected.size > 0 ? `${selected.size} selected` : "Select all"}
            />
            <Button
              variant="ink"
              size="sm"
              disabled={selected.size === 0 || bulkApprove.isPending}
              onClick={() => handleBulkApprove(items)}
            >
              {bulkApprove.isPending
                ? "Approving…"
                : `Bulk-approve${selected.size > 0 ? ` (${selected.size})` : ""}`}
            </Button>
            <span className="text-body-sm text-ink-faint">
              Accepts each selected mark exactly as Lemely awarded it. Integrity flags aren't
              selectable here. Open one to look at it properly.
            </span>
          </div>

          {bulkApprove.isError ? (
            <div role="alert" className="text-body-sm text-err">
              Couldn't bulk-approve: {teacherMutationFailureMessage(bulkApprove.error)}
            </div>
          ) : null}

          {bulkResult ? (
            <div
              role="status"
              className="border border-rule rounded-md p-4 bg-paper-sunk flex flex-col gap-2"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-body-md font-medium">
                  Approved {bulkResult.approved.length} item
                  {bulkResult.approved.length === 1 ? "" : "s"}
                  {bulkResult.skipped.length > 0 ? ` · skipped ${bulkResult.skipped.length}` : "."}
                </div>
                <Button variant="ghost" size="sm" onClick={() => setBulkResult(null)}>
                  Dismiss
                </Button>
              </div>
              {bulkResult.skipped.length > 0 ? (
                <ul className="flex flex-col gap-1 text-body-sm text-ink-muted m-0 ps-4 list-disc">
                  {bulkResult.skipped.map((s) => {
                    const row = snapshotRef.current.find((r) => r.itemId === s.itemId)
                    return (
                      <li key={s.itemId}>
                        {row ? `${row.studentDisplayName} — ${questionLabel(row)}` : s.itemId}
                        {": "}
                        {SKIP_REASON_LABEL[s.reason] ?? s.reason}
                      </li>
                    )
                  })}
                </ul>
              ) : null}
            </div>
          ) : null}

          <div
            className="bg-paper-raised border border-rule rounded-lg overflow-hidden overflow-x-auto min-w-0"
            tabIndex={0}
            role="region"
            aria-label="Review queue, scrollable horizontally"
          >
            <table className="w-full text-body-md border-collapse">
              <caption className="sr-only">
                Review queue, oldest-waiting item first, which is the priority order the server already
                returns this list in
              </caption>
              <thead>
                <tr className="bg-paper-sunk border-b border-rule">
                  <th scope="col" className="px-[16px] py-[10px]">
                    <span className="sr-only">Select</span>
                  </th>
                  <th
                    scope="col"
                    className="text-start px-[16px] py-[10px] text-eyebrow text-ink-faint"
                  >
                    Student
                  </th>
                  <th
                    scope="col"
                    className="text-start px-[16px] py-[10px] text-eyebrow text-ink-faint"
                  >
                    Paper
                  </th>
                  <th
                    scope="col"
                    className="text-start px-[16px] py-[10px] text-eyebrow text-ink-faint"
                  >
                    Question
                  </th>
                  <th
                    scope="col"
                    className="text-start px-[16px] py-[10px] text-eyebrow text-ink-faint"
                  >
                    Why it's here
                  </th>
                  <th
                    scope="col"
                    className="text-start px-[16px] py-[10px] text-eyebrow text-ink-faint"
                  >
                    Waiting
                  </th>
                  <th
                    scope="col"
                    className="text-end px-[16px] py-[10px] text-eyebrow text-ink-faint whitespace-nowrap"
                  >
                    AI mark
                  </th>
                  <th
                    scope="col"
                    className="text-end px-[16px] py-[10px] text-eyebrow text-ink-faint"
                  >
                    Confidence
                  </th>
                  <th scope="col" className="px-[16px] py-[10px]">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.itemId} className="border-b border-rule last:border-b-0 align-top">
                    <td className="px-[16px] py-[13px]">
                      <Checkbox
                        checked={selected.has(item.itemId)}
                        disabled={isIntegrityReason(item.reason)}
                        onChange={() => toggleSelected(item.itemId)}
                        title={
                          isIntegrityReason(item.reason)
                            ? "Integrity flags aren't selectable for bulk-approve. Open this item instead"
                            : undefined
                        }
                        aria-label={
                          isIntegrityReason(item.reason)
                            ? `${item.studentDisplayName}'s ${questionLabel(item)} is an integrity flag and isn't selectable here. Open it instead`
                            : `Select ${item.studentDisplayName}'s ${questionLabel(item)} for bulk approve`
                        }
                      />
                    </td>
                    <td className="px-[16px] py-[13px]">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Avatar name={item.studentDisplayName} size="sm" />
                        <div className="min-w-0">
                          <Link
                            to={`/teacher/students/${item.studentId}`}
                            className="text-ink hover:underline block truncate"
                          >
                            {item.studentDisplayName}
                          </Link>
                          <Link
                            to={`/teacher/classes/${item.classId}`}
                            className="text-body-sm text-ink-faint transition-colors hover:text-ink hover:underline block truncate"
                          >
                            {item.className}
                          </Link>
                        </div>
                      </div>
                    </td>
                    <td className="px-[16px] py-[13px] whitespace-nowrap text-body-sm text-ink-muted">
                      {paperIdentityLabel(item)}
                    </td>
                    <td className="px-[16px] py-[13px] text-data-sm whitespace-nowrap">
                      {item.questionId ?? "—"}
                    </td>
                    <td className="px-[16px] py-[13px]">
                      <Chip tone={isIntegrityReason(item.reason) ? "warn" : "neutral"}>
                        {reasonLabel(item.reason)}
                      </Chip>
                    </td>
                    <td className="px-[16px] py-[13px] whitespace-nowrap text-body-sm text-ink-muted">
                      {relativeTime(item.createdAt)}
                    </td>
                    {/* The confidence gets its own column rather than sitting
                        unlabelled under the mark. Stacked, a tone-coloured
                        "85%" read as a second figure about the *mark* — the
                        same shape as surface 4's unlabelled rank column, where
                        a coloured number beside another number invited the two
                        to be read as a pair. A percentage under "2/3" is
                        especially open to being read as a score. */}
                    <td className="px-[16px] py-[13px] text-end whitespace-nowrap">
                      <div className="text-data-sm text-ink">
                        {item.aiAwardedMarks ?? "–"}/{item.maximumMarks ?? "–"}
                      </div>
                    </td>
                    <td className="px-[16px] py-[13px] text-end whitespace-nowrap">
                      {item.confidenceScore != null ? (
                        <Chip tone={confidenceTone(item.confidenceScore)}>
                          {Math.round(item.confidenceScore * 100)}%
                        </Chip>
                      ) : (
                        <span className="text-body-sm text-ink-faint">–</span>
                      )}
                    </td>
                    <td className="px-[16px] py-[13px] text-end whitespace-nowrap">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          navigate(
                            `/teacher/review/${item.itemId}${filterQsString ? `?${filterQsString}` : ""}`,
                          )
                        }
                      >
                        Review →
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

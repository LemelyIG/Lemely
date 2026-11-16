/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useRef, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { Funnel } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Select } from "@/components/ui/select"
import { SectionHead } from "@/components/ui/section-head"
import { Chip } from "@/components/ui/chip"
import { EmptyState } from "@/components/ui/state-views"
import { relativeTime } from "@/lib/utils"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import {
  teacherLoadFailureMessage,
  teacherMutationFailureMessage,
} from "@/lib/teacherOutcome"
import { Avatar } from "@/components/ui/avatar"
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/table"
import { useBulkApproveReview, useReviewQueue, useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import type { BulkApproveResponse, ReviewQueueItem, ReviewQueueList } from "@/lib/teacherTypes"
import { ForwardArrow } from "@/components/ui/inline-arrow"
import { ListGroup, ListRow } from "@/components/ui/list-group"
import { TableOrList } from "@/components/ui/table-or-list"
import { Modal } from "@/components/ui/modal"
import { useNativeFrame } from "@/lib/useNativeFrame"
import {
  AGE_FILTER_OPTIONS,
  REASON_FILTER_OPTIONS,
  SKIP_REASON_LABEL,
  confidenceTone,
  isConsolePaperItem,
  isIntegrityReason,
  mergeReviewPages,
  paperIdentityLabel,
  reasonLabel,
} from "./review/reviewLabels"

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
 * **`manual`/`random_audit` are deliberately excluded from the reason
 * filter.** `ReviewQueueItem` rows have two production producers —
 * `AttemptRepository.persist_correction` for a student attempt and
 * `_review_items_for` (`teacher_paper_repo.py`) for a console-graded paper
 * — and both route through the same `review_reasons_for`
 * (`review_queue_rules.py`), which only ever yields `low_confidence` or
 * `plagiarism_flag`. Neither producer writes `manual` or `random_audit`.
 * (Migration `0037` did write
 * `manual` once, as the one-way rewrite target for the now-removed
 * AI-generated-answer detector's flag — but that is historical data from a
 * schema migration, not something the live pipeline produces, so it stays
 * out of the filter for the same reason `random_audit`, N2's still-unbuilt
 * sampler, does.) Offering a filter option that can never match a row the
 * live pipeline creates would imply data this build doesn't have — the same
 * reasoning that used to keep `below_target` out of `AtRiskList.tsx`'s
 * reason filter before P4.3/D4.5 wired up a real target grade there.
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

/** "0625 P2/1 · May 2026": the paper in the width a phone row can hold. */
function compactPaperLabel(item: ReviewQueueItem): string {
  if (!item.subjectCode) return "Quiz question"
  const paper =
    item.paperNumber != null ? ` P${item.paperNumber}${item.paperVariant != null ? `/${item.paperVariant}` : ""}` : ""
  const session = item.sessionMonth && item.sessionYear ? ` · ${item.sessionMonth} ${item.sessionYear}` : ""
  return `${item.subjectCode}${paper}${session}`
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
  const filterKey = `${classId}|${reason}|${minAgeHours}`

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkResult, setBulkResult] = useState<BulkApproveResponse | null>(null)
  const snapshotRef = useRef<ReviewQueueItem[]>([])

  // Task 11 (B6c): "Load more" cursor pagination (T-09's `nextCursor`).
  // `cursor` resets to `undefined` whenever the filter tuple changes (the
  // effect below); `pages` accumulates every fetched page under the current
  // filters via `mergeReviewPages` above.
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [pages, setPages] = useState<{ key: string; items: ReviewQueueItem[] }>({ key: "", items: [] })
  // The guard that lets the merge below run once per *new* query result
  // rather than once per render — "adjusting state during render" (React's
  // own documented pattern for this), not a `useEffect`, because an effect
  // would commit one frame with the stale accumulated `pages` before
  // catching up, which is exactly the frame a click on "Load more" paints.
  const [mergedData, setMergedData] = useState<ReviewQueueList | undefined>(undefined)

  const classesQuery = useTeacherClasses()
  const queueQuery = useReviewQueue({
    classId: classId || undefined,
    reason: reason || undefined,
    minAgeHours: minAgeHours ? Number(minAgeHours) : undefined,
    limit: 50,
    cursor,
  })
  const bulkApprove = useBulkApproveReview()
  const { native } = useNativeFrame()
  const [filterOpen, setFilterOpen] = useState(false)

  if (queueQuery.data && queueQuery.data !== mergedData) {
    setMergedData(queueQuery.data)
    setPages((prev) => mergeReviewPages(prev, { key: filterKey, items: queueQuery.data!.items }))
  }

  // A selection made under one filter combination shouldn't silently carry
  // over (and get bulk-approved) once the visible set changes underneath it.
  // The same filter change also restarts pagination from the first page —
  // `mergeReviewPages` itself would replace `pages` regardless once the new
  // page's `key` arrives, but resetting `cursor` here is what makes that the
  // *first* page rather than whatever page the old filters had scrolled to.
  useEffect(() => {
    setSelected(new Set())
    setCursor(undefined)
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

  return (
    <div className="flex flex-col gap-6 min-w-0">
      <QueryState
        query={queueQuery}
        srHeading="Review queue"
        skeleton={
          <>
            <PageHeaderSkeleton />
            <ListSkeleton rows={6} avatar />
          </>
        }
        error={{
          heading: "Couldn't load the review queue",
          body: teacherLoadFailureMessage,
        }}
      >
        {() => {
          // Task 11 (B6c): the accumulated pages, not the query's own
          // `data.items` — a single fetch is one page; `pages.items` is
          // every page "Load more" has pulled in under the current filters.
          const items = pages.items
          const filterQsString = searchParams.toString()
          const filtersActive = classId !== "" || reason !== "" || minAgeHours !== ""
          const selectableItems = selectableOf(items)
          const allSelected =
            selectableItems.length > 0 && selectableItems.every((i) => selected.has(i.itemId))

          const activeFilterCount = [classId, reason, minAgeHours].filter((v) => v !== "").length
          const filterButton = (
            <Button
              variant="secondary"
              size="sm"
              icon={<Funnel size={16} />}
              aria-haspopup="dialog"
              aria-label={activeFilterCount > 0 ? `Filter, ${activeFilterCount} applied` : "Filter"}
              data-review-filter
              onClick={() => setFilterOpen(true)}
            >
              Filter
              {activeFilterCount > 0 ? (
                <span
                  data-filter-count
                  aria-hidden="true"
                  className="ms-1 inline-flex min-w-5 items-center justify-center rounded-pill bg-primary px-1.5 text-3xs text-on-primary"
                >
                  {activeFilterCount}
                </span>
              ) : null}
            </Button>
          )
          const filterControls = (
            <>
                <Select
                label="Class"
                value={classId}
                onChange={(e) => updateFilter("class_id", e.target.value)}
                wrapperClassName="min-w-[170px]"
              >
                <option value="">All classes</option>
                {(classesQuery.data?.classes ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </Select>
              <Select label="Reason" value={reason} onChange={(e) => updateFilter("reason", e.target.value)}>
                {REASON_FILTER_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
              <Select
                label="Waiting at least"
                value={minAgeHours}
                onChange={(e) => updateFilter("min_age_hours", e.target.value)}
              >
                {AGE_FILTER_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </>
          )

          return (
            <>
              <SectionHead
                eyebrow="The teacher's core recurring task"
                title="Review queue"
                kicker="Low-confidence marks and integrity flags land here, oldest first. Bulk-approve the trivially fine ones. Open anything that needs a real look."
                rung="display-md"
                level={1}
                repeatsTitle={true}
              />

              {native ? (
                <Modal
                  open={filterOpen}
                  onClose={() => setFilterOpen(false)}
                  title="Filter the review queue"
                  size="sm"
                  footer={
                    <>
                      {activeFilterCount > 0 ? (
                        <Button variant="secondary" onClick={() => setSearchParams({}, { replace: true })}>
                          Clear filters
                        </Button>
                      ) : null}
                      <Button variant="primary" onClick={() => setFilterOpen(false)}>
                        Done
                      </Button>
                    </>
                  }
                >
                  <div className="flex flex-col gap-3">{filterControls}</div>
                </Modal>
              ) : (
                <div className="flex items-end gap-4 flex-wrap">{filterControls}</div>
              )}
              {/* With rows, Filter shares the View table row (TableOrList `toolbar`); an empty
                  queue has no such row, so Filter stands alone and a filter can still be cleared. */}
              {native && items.length === 0 ? <div className="flex justify-start">{filterButton}</div> : null}

              {/*
               * The empty branch stays inside `children` rather than going
               * through `QueryState`'s own `isEmpty`/`empty`: the header and
               * the three filter controls above must render identically in
               * both the empty and non-empty cases (so a teacher can clear a
               * filter that zeroed the list), and `empty` is a single fixed
               * `ReactNode` — hoisting just the `EmptyState` there would mean
               * keeping two copies of that filter markup (one in `children`,
               * one in `empty`) in sync by hand, which is the exact kind of
               * per-screen drift this PR exists to close.
               */}
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
                  <TableOrList
                    label="Review queue"
                    toolbar={filterButton}
                    storageKey="lemely.review.view"
                    onListView={() => setSelected((prev) => (prev.size === 0 ? prev : new Set()))}
                    tableHeader={
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
                        <span className="text-body-sm text-on-surface-variant">
                          Accepts each selected mark exactly as Lemely awarded it. Integrity flags aren't
                          selectable here. Open one to look at it properly.
                        </span>
                      </div>
                    }
                    notices={
                      <>
                        {bulkApprove.isError ? (
                          <div role="alert" className="text-body-sm text-error">
                            Couldn't bulk-approve: {teacherMutationFailureMessage(bulkApprove.error)}
                          </div>
                        ) : null}

                        {bulkResult ? (
                          <div
                            role="status"
                            className="border border-outline-variant rounded-md p-4 bg-surface-container-low flex flex-col gap-2"
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
                              <ul className="flex flex-col gap-1 text-body-sm text-on-surface-variant m-0 ps-4 list-disc">
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
                      </>
                    }
                    list={
                      <ListGroup>
                        {items.map((item) => (
                          <ListRow
                            key={item.itemId}
                            to={`/teacher/review/${item.itemId}${filterQsString ? `?${filterQsString}` : ""}`}
                            title={item.studentDisplayName}
                            titleLines={2}
                            lines={3}
                            subtitle={
                              <>
                                <span data-review-question className="block">
                                  {item.questionId ? questionLabel(item) : "No question"} · {compactPaperLabel(item)}
                                </span>
                                <Chip tone={isIntegrityReason(item.reason) ? "warn" : "neutral"} className="mt-1">
                                  {reasonLabel(item.reason)}
                                </Chip>
                              </>
                            }
                            trailing={
                              item.confidenceScore != null ? (
                                <Chip tone={confidenceTone(item.confidenceScore)} data-review-confidence>
                                  {Math.round(item.confidenceScore * 100)}%
                                </Chip>
                              ) : (
                                <span className="text-body-sm">–</span>
                              )
                            }
                          />
                        ))}
                      </ListGroup>
                    }
                    table={
                      <Table density="operate"
                        tabIndex={0}
                        role="region"
                        aria-label="Review queue, scrollable horizontally"
                      >
                        <caption className="sr-only">
                          Review queue, oldest-waiting item first, which is the priority order the server already
                          returns this list in
                        </caption>
                        <THead>
                          <TR>
                            <TH>
                              <span className="sr-only">Select</span>
                            </TH>
                            <TH>Student</TH>
                            <TH>Paper</TH>
                            <TH>Question</TH>
                            <TH>Why it's here</TH>
                            <TH>Waiting</TH>
                            <TH numeric>AI mark</TH>
                            <TH numeric>Confidence</TH>
                            <TH>
                              <span className="sr-only">Actions</span>
                            </TH>
                          </TR>
                        </THead>
                        <TBody>
                          {items.map((item) => (
                            <TR key={item.itemId} className="align-top">
                              <TD>
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
                              </TD>
                              <TD>
                                {/* Two row shapes, because the queue has two
                                    sources. A console-uploaded paper has no
                                    student and no class (D1.12), so it gets
                                    neither an avatar nor the two links below:
                                    rendering a person's avatar for a scan, or a
                                    link to `/teacher/students/null`, would be
                                    inventing a student this row does not have. */}
                                {isConsolePaperItem(item) ? (
                                    <div className="flex items-center gap-2.5 min-w-0">
                                      <span
                                        aria-hidden="true"
                                        className="flex-none w-8 h-8 rounded-full bg-surface-container-low border border-outline-variant flex items-center justify-center text-on-surface-variant"
                                      >
                                        <svg
                                          viewBox="0 0 16 16"
                                          className="w-3.5 h-3.5"
                                          fill="none"
                                          stroke="currentColor"
                                          strokeWidth="1.5"
                                        >
                                          <path d="M9.5 1.5H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5z" />
                                          <path d="M9.5 1.5V5H13" />
                                        </svg>
                                      </span>
                                      <div className="min-w-0 max-w-[20ch]">
                                        <Link
                                          to="/teacher/grading"
                                          className="flex items-center text-on-surface hover:underline pointer-coarse:min-h-11"
                                        >
                                          <span className="truncate">{item.studentDisplayName}</span>
                                        </Link>
                                        <span className="flex items-center text-body-sm text-on-surface-variant">
                                          Grading console
                                        </span>
                                      </div>
                                    </div>
                                  ) : (
                                  <div className="flex items-center gap-2.5 min-w-0">
                                    <Avatar name={item.studentDisplayName} size="sm" />
                                    {/* P6.2's long-content pass. `min-w-0` alone could not
                                        make the `truncate` below fire, and this is the
                                        first capture that ever rendered a name long enough
                                        to show it: the table is `w-full` with the default
                                        `table-layout: auto`, so a long name grows its own
                                        cell, drags the table past the card, and the text is
                                        CLIPPED by the `overflow-x-auto` wrapper rather than
                                        ellipsised. The rule was correct and unreachable —
                                        present, resolving, and unable to fire, which no
                                        gate in this build can see.

                                        What the capture showed is worse than a missing
                                        ellipsis, and it is why this is bounded rather than
                                        left to scroll: at 1440, one long name widened the
                                        student column by ~170px and pushed the per-row
                                        "Review →" button off the right edge of the card.
                                        The action every row exists for became unreachable
                                        without horizontal scrolling, on a desktop screen
                                        with room to spare, because of one student's name.

                                        A character measure rather than a pixel width, for
                                        the same reason `CorrectPaper`'s `max-w-[60ch]` is
                                        one: it is a count of glyphs, not a spacing value,
                                        so it is out of scope for the 4px scale. 20ch is
                                        about the column's own natural width, so it is a
                                        `max` that ordinary names never reach and long ones
                                        cannot exceed. 30ch was tried first and did not
                                        bind — it truncated the name and the table still
                                        grew. */}
                                    {/* One link to the student with the class as plain text under
                                        the name, so the cell has one target and it carries §6.1's
                                        44px floor (`min-h-11`, flex-centred) on a finger. The class
                                        used to be a second link; two stacked links in one 44px cell
                                        each fall under the floor. `truncate` sits on inner spans:
                                        on a flex container the text is an anonymous flex item and
                                        text-overflow has nothing to apply to. */}
                                    <Link
                                      to={`/teacher/students/${item.studentId}`}
                                      className="flex min-w-0 max-w-[20ch] flex-col justify-center text-on-surface hover:underline pointer-coarse:min-h-11"
                                    >
                                      <span className="truncate">{item.studentDisplayName}</span>
                                      <span className="truncate text-body-sm text-on-surface-variant">{item.className}</span>
                                    </Link>
                                  </div>
                                  )}
                              </TD>
                              <TD className="whitespace-nowrap text-body-sm text-on-surface-variant">
                                {paperIdentityLabel(item)}
                              </TD>
                              <TD className="text-data-sm whitespace-nowrap">
                                {item.questionId ?? "—"}
                              </TD>
                              <TD>
                                <Chip tone={isIntegrityReason(item.reason) ? "warn" : "neutral"}>
                                  {reasonLabel(item.reason)}
                                </Chip>
                              </TD>
                              <TD className="whitespace-nowrap text-body-sm text-on-surface-variant">
                                {relativeTime(item.createdAt)}
                              </TD>
                              {/* The confidence gets its own column rather than sitting
                                  unlabelled under the mark. Stacked, a tone-coloured
                                  "85%" read as a second figure about the *mark* — the
                                  same shape as surface 4's unlabelled rank column, where
                                  a coloured number beside another number invited the two
                                  to be read as a pair. A percentage under "2/3" is
                                  especially open to being read as a score. */}
                              <TD numeric className="whitespace-nowrap text-data-sm">
                                {item.aiAwardedMarks ?? "–"}/{item.maximumMarks ?? "–"}
                              </TD>
                              <TD numeric className="whitespace-nowrap">
                                {item.confidenceScore != null ? (
                                  <Chip tone={confidenceTone(item.confidenceScore)}>
                                    {Math.round(item.confidenceScore * 100)}%
                                  </Chip>
                                ) : (
                                  <span className="text-body-sm text-on-surface-variant">–</span>
                                )}
                              </TD>
                              <TD className="text-end whitespace-nowrap">
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  onClick={() =>
                                    navigate(
                                      `/teacher/review/${item.itemId}${filterQsString ? `?${filterQsString}` : ""}`,
                                    )
                                  }
                                >
                                  Review <ForwardArrow />
                                </Button>
                              </TD>
                            </TR>
                          ))}
                        </TBody>
                      </Table>
                    }
                  />

                  {/* Task 11 (B6c): keyset "Load more", not a virtualized
                      list or infinite scroll — deferred by design. The
                      review queue is a bounded working set a teacher clears
                      out (bulk-approve, resolve, dismiss), not an
                      ever-growing feed, so the DOM-node-count problem
                      virtualization solves does not apply here the way it
                      would to e.g. a chat history; revisit if that
                      assumption stops holding. */}
                  {mergedData?.nextCursor ? (
                    <div className="flex justify-center">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={queueQuery.isFetching}
                        onClick={() => setCursor(mergedData.nextCursor ?? undefined)}
                      >
                        {queueQuery.isFetching ? "Loading…" : "Load more"}
                      </Button>
                    </div>
                  ) : null}
                </>
              )}
            </>
          )
        }}
      </QueryState>
    </div>
  )
}

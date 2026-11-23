import type { BinnyMood } from "@/components/redesign"
import type { ReviewQueueFilters } from "@/lib/reviewQueueQuery"
import { EMPTY_FILTERS } from "@/lib/reviewQueueQuery"
import type { ReviewQueueItem, ReviewSort } from "@/lib/teacherTypes"
import {
  AGE_FILTER_OPTIONS,
  REASON_FILTER_OPTIONS,
  isConsolePaperItem,
  isIntegrityReason,
  reasonLabel,
} from "./reviewLabels"

/**
 * The review queue's "clear" band, from the approved design (review-r1
 * final2: red ring under 70%, gold from 70%; "Approve clear" takes only
 * these). It is deliberately NOT the backend's single review threshold
 * (0.90, `lib/markingConfidence.ts`): every row here is already below that
 * one. This is the product's second, named band for "unsure, but probably
 * fine", and it is used for exactly two things: the ring colour and the
 * "Approve N clear" set. See the L5 plan, Needs user decision #1.
 */
export const CLEAR_CONFIDENCE = 0.7

export type RingTone = "warn" | "gold" | "neutral"

export function ringTone(score: number | null): RingTone {
  if (score == null) return "neutral"
  return score >= CLEAR_CONFIDENCE ? "gold" : "warn"
}
export function ringValue(score: number | null): number {
  return score == null ? 0 : Math.min(1, Math.max(0, score))
}
export function ringText(score: number | null): string {
  return score == null ? "–" : String(Math.round(score * 100))
}
export function ringLabel(score: number | null): string {
  return score == null ? "No confidence score" : `${Math.round(score * 100)}% sure`
}

const SESSION_SHORT: Record<string, string> = {
  "May/June": "m/j",
  "Oct/Nov": "o/n",
  "Feb/Mar": "f/m",
  Specimen: "specimen",
}
export function sessionShort(month: string | null): string | null {
  if (!month) return null
  return SESSION_SHORT[month] ?? month
}

type PaperBits = Pick<ReviewQueueItem, "subjectCode" | "paperNumber" | "paperVariant" | "sessionMonth" | "sessionYear">

export function paperCode(item: PaperBits): string | null {
  if (!item.subjectCode || item.paperNumber == null) return item.subjectCode ?? null
  return `${item.subjectCode}/${item.paperNumber}${item.paperVariant ?? ""}`
}

/** "0580/42 · m/j 2025": the panel subtitle's paper part (K8: "Quiz question"). */
export function paperLine(item: PaperBits): string {
  if (!item.subjectCode) return "Quiz question"
  const code = paperCode(item) ?? item.subjectCode
  const month = sessionShort(item.sessionMonth)
  return month && item.sessionYear ? `${code} · ${month} ${item.sessionYear}` : code
}

export function questionLabel(item: Pick<ReviewQueueItem, "questionId">): string {
  return item.questionId ? `Q${item.questionId}` : "Question"
}

export function rowSubtitle(item: ReviewQueueItem): string {
  const who = isConsolePaperItem(item) ? "Grading console" : (item.className ?? "")
  return [who, questionLabel(item)].filter(Boolean).join(" · ")
}

/**
 * One short plain line per review reason, keyed by reason. This is the only
 * place a reason becomes row copy: add a reason (L7's `student_challenge`)
 * by adding a key here. `low_confidence` is the default for that reason;
 * `LOW_CONFIDENCE_WHY` refines it from the marker's technical text.
 */
export const REASON_PLAIN: Record<string, string> = {
  low_confidence: "Lemely wasn't sure",
  plagiarism_flag: "Matches mark-scheme wording",
  student_evidence_unjudged: "Student challenged a mark",
  manual: "Flagged by hand",
  random_audit: "Random check",
}

/** Ordered: the first needle found in the marker's reviewReason wins. */
const LOW_CONFIDENCE_WHY: [needle: string, line: string][] = [
  ["missing answer", "No answer found"],
  ["invalid mcq", "Unclear choice"],
  ["mcq_answer", "Scheme has no answer key"],
  ["unverified accuracy", "Final answer not confirmed"],
  ["extraction confidence", "Hard to read"],
  ["point_verdicts", "Marks and points don't match"],
  ["mark point id", "Marks and points don't match"],
]

/** An unmapped reason ("student_challenge") reads as plain words, never the raw key. */
function humanizeReason(reason: string): string {
  const words = reason.replace(/[_-]+/g, " ").trim().toLowerCase()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Needs a look"
}

/**
 * The marker's `reviewReason` is technical ("confidence 0.62 below review
 * threshold 0.90"); teachers get words, never the raw string (it stays in
 * the panel's "Lemely's notes").
 */
export function plainWhy(item: Pick<ReviewQueueItem, "reason" | "reviewReason">): string {
  if (item.reason === "low_confidence") {
    const r = (item.reviewReason ?? "").toLowerCase()
    return LOW_CONFIDENCE_WHY.find(([needle]) => r.includes(needle))?.[1] ?? REASON_PLAIN.low_confidence
  }
  return REASON_PLAIN[item.reason] ?? humanizeReason(item.reason)
}

export function marksLost(item: Pick<ReviewQueueItem, "aiAwardedMarks" | "maximumMarks">): number | null {
  if (item.aiAwardedMarks == null || item.maximumMarks == null) return null
  return item.maximumMarks - item.aiAwardedMarks
}

export function selectable(item: Pick<ReviewQueueItem, "reason">): boolean {
  return !isIntegrityReason(item.reason)
}
export function isClearItem(item: Pick<ReviewQueueItem, "reason" | "confidenceScore">): boolean {
  return selectable(item) && item.confidenceScore != null && item.confidenceScore >= CLEAR_CONFIDENCE
}

export function bulkButton(s: { selecting: boolean; picked: number; clearCount: number; pending: boolean }): {
  label: string
  disabled: boolean
} {
  if (s.pending) return { label: "Approving…", disabled: true }
  if (s.selecting) {
    return s.picked > 0
      ? { label: `Approve ${s.picked} selected`, disabled: false }
      : { label: "Pick answers to approve", disabled: true }
  }
  return s.clearCount > 0
    ? { label: `Approve ${s.clearCount} clear`, disabled: false }
    : { label: "No clear answers", disabled: true }
}

export type QueueScreenState =
  | "loading"
  | "error"
  | "first-run"
  | "nothing-waiting"
  | "cleared"
  | "no-match"
  | "sparse"
  | "queue"

export type QueueQueryStatus = "pending" | "error" | "success"

/**
 * A failure only takes the whole screen when there is nothing to show. Cached `data` (a refetch that
 * failed) or `heldRows` for the current filter (a later page that failed) both keep the list up.
 */
export function queueQueryStatus(status: QueueQueryStatus, data: unknown, heldRows = 0): QueueQueryStatus {
  return status === "error" && (data !== undefined || heldRows > 0) ? "success" : status
}

/**
 * What the screen reads from the queue query. A page past the first has its own query key, so when it
 * fails it has no data of its own (react-query drops the placeholder) while the merged rows are still
 * held. `held` is the last good page for `key`, `heldRows` the rows on screen for `key`.
 * - `page`: where total, cursor, subjects and history come from: the live page, else the held one.
 * - `status`: what `queueScreenState` sees.
 * - `moreFailed`: the query failed with rows on screen, so keep them and retry beside Load more.
 */
export function queueLoad<T>(
  query: { status: QueueQueryStatus; data: T | undefined; isPlaceholderData?: boolean },
  held: { key: string; data: T } | null,
  key: string,
  heldRows: number,
): { page: T | undefined; status: QueueQueryStatus; moreFailed: boolean } {
  const currentHeld = held?.key === key ? held.data : undefined
  const data = query.isPlaceholderData ? currentHeld : query.data
  return {
    page: data ?? currentHeld,
    status: query.isPlaceholderData && !currentHeld ? "pending" : queueQueryStatus(query.status, data, heldRows),
    moreFailed: query.status === "error" && query.data === undefined && heldRows > 0,
  }
}

/** The Load more cursor and the filter it belongs to. */
export interface PagingCursor {
  key: string
  cursor: string
}

/**
 * A cursor is only ever read under the filter that produced it. Run on every render and written back when it
 * changes, so a filter change drops the cursor in the same render (no effect in between) and returning to an
 * earlier filter starts again at its first page instead of resuming at a page the rows no longer include.
 */
export function reconcileCursor(state: PagingCursor | null, key: string): PagingCursor | null {
  return state?.key === key ? state : null
}

/**
 * The cursor Load more may use, or nothing. Only real data pages: while the query shows a placeholder (the
 * previous filter's page, or this filter's own next page still loading) the cursor on screen is not the one
 * to advance from, and using it could skip the first page of a new filter.
 */
export function pageableCursor(query: { isPlaceholderData?: boolean }, page: { nextCursor: string | null } | undefined): string | undefined {
  return query.isPlaceholderData ? undefined : (page?.nextCursor ?? undefined)
}

/**
 * Load more is in flight: this filter's next page is loading (shown as the held page, so a placeholder) or a
 * failed one is being retried. A background refetch of a page already on screen (the invalidation a resolve
 * schedules) is neither, so it must not flip the control to "Loading…" or announce it.
 */
export function isLoadingMore(query: { isFetching: boolean; isPlaceholderData?: boolean; isError?: boolean }, cursor: string | undefined): boolean {
  return !!cursor && query.isFetching && (!!query.isPlaceholderData || !!query.isError)
}

export function queueScreenState(s: {
  status: "pending" | "error" | "success"
  visibleCount: number
  openTotal: number
  filtersActive: boolean
  hasHistory: boolean
  decidedThisSession: number
  moreFailed?: boolean
  /** The server has a next page. With every loaded row resolved the list is empty, not cleared. */
  moreRemain?: boolean
}): QueueScreenState {
  if (s.status === "pending") return "loading"
  if (s.status === "error") return "error"
  if (s.moreFailed) return "queue"
  if (s.visibleCount === 0) {
    if (s.moreRemain) return "queue"
    if (s.filtersActive) return "no-match"
    if (s.decidedThisSession > 0) return "cleared"
    return s.hasHistory ? "nothing-waiting" : "first-run"
  }
  if (s.visibleCount === 1 && s.openTotal === 1 && !s.filtersActive) return "sparse"
  return "queue"
}

/** Teacher Binny: a small head-crop, calm states only, one per screen. */
export function binnyFor(state: QueueScreenState): { mood: BinnyMood } | null {
  if (state === "first-run") return { mood: "open" }
  if (state === "nothing-waiting" || state === "cleared") return { mood: "happy" }
  return null
}

export function headerTitle(left: number, done: number): string {
  return `${left === 1 ? "answer" : "answers"} left · ${done} done`
}
export function progressOf(left: number, done: number): number {
  const all = left + done
  return all === 0 ? 0 : done / all
}

export interface Tally {
  decided: number
  changed: number
  dismissed: number
}
export function clearedSummary(t: Tally): string {
  return `${t.decided} decided · ${t.changed} ${t.changed === 1 ? "mark" : "marks"} changed · ${t.dismissed} dismissed`
}
export function shownLine(shown: number, total: number): string {
  return `Showing ${shown} of ${total}`
}

export type FilterCategory = "reason" | "class" | "paper" | "waiting"
export interface FilterOptions {
  classes: { id: string; label: string }[]
  subjects: string[]
  subjectName: (code: string) => string
}
export interface FilterChip {
  category: FilterCategory
  value: string
  label: string
}
const CATEGORY_LABEL: Record<FilterCategory, string> = {
  reason: "Reason",
  class: "Class",
  paper: "Paper",
  waiting: "Waiting",
}
const REASONS = REASON_FILTER_OPTIONS.filter((o) => o.value !== "")
const AGES = AGE_FILTER_OPTIONS.filter((o) => o.value !== "")

function valuesOf(f: ReviewQueueFilters, c: FilterCategory): string[] {
  if (c === "reason") return f.reasons
  if (c === "class") return f.classIds
  if (c === "paper") return f.subjects
  return f.minAgeHours === null ? [] : [String(f.minAgeHours)]
}

function labelOf(c: FilterCategory, v: string, o: FilterOptions): string {
  if (c === "reason") return REASONS.find((r) => r.value === v)?.label ?? reasonLabel(v)
  if (c === "class") return o.classes.find((k) => k.id === v)?.label ?? "Class"
  if (c === "paper") {
    const name = o.subjectName(v)
    return name && name !== v ? `${v} ${name}` : v
  }
  return AGES.find((a) => a.value === v)?.label ?? `${v}+ hours`
}

export function filterCategories(f: ReviewQueueFilters): { key: FilterCategory; label: string; count: number }[] {
  return (Object.keys(CATEGORY_LABEL) as FilterCategory[]).map((key) => ({
    key,
    label: CATEGORY_LABEL[key],
    count: valuesOf(f, key).length,
  }))
}

export function filterValues(
  c: FilterCategory,
  f: ReviewQueueFilters,
  o: FilterOptions,
): { value: string; label: string; checked: boolean }[] {
  const chosen = new Set(valuesOf(f, c))
  const values =
    c === "reason"
      ? REASONS.map((r) => r.value)
      : c === "class"
        ? o.classes.map((k) => k.id)
        : c === "paper"
          ? o.subjects
          : AGES.map((a) => a.value)
  return values.map((value) => ({ value, label: labelOf(c, value, o), checked: chosen.has(value) }))
}

function toggled(xs: string[], v: string): string[] {
  return xs.includes(v) ? xs.filter((x) => x !== v) : [...xs, v]
}

export function toggleFilter(f: ReviewQueueFilters, c: FilterCategory, v: string): ReviewQueueFilters {
  if (c === "reason") return { ...f, reasons: toggled(f.reasons, v) }
  if (c === "class") return { ...f, classIds: toggled(f.classIds, v) }
  if (c === "paper") return { ...f, subjects: toggled(f.subjects, v) }
  const hours = Number(v)
  return { ...f, minAgeHours: f.minAgeHours === hours ? null : hours }
}

export function removeFilter(f: ReviewQueueFilters, c: FilterCategory, v: string): ReviewQueueFilters {
  if (c === "waiting") return { ...f, minAgeHours: null }
  return valuesOf(f, c).includes(v) ? toggleFilter(f, c, v) : f
}

/** Clears every filter and the search; keeps the teacher's chosen sort. */
export function clearFilters(f: ReviewQueueFilters): ReviewQueueFilters {
  return { ...EMPTY_FILTERS, sort: f.sort }
}

export function filterChips(f: ReviewQueueFilters, o: FilterOptions): FilterChip[] {
  const chips: FilterChip[] = []
  for (const c of ["reason", "class", "paper", "waiting"] as const) {
    for (const v of valuesOf(f, c)) chips.push({ category: c, value: v, label: `${CATEGORY_LABEL[c]}: ${labelOf(c, v, o)}` })
  }
  return chips
}

export const SORT_OPTIONS: { value: ReviewSort; label: string }[] = [
  { value: "lost", label: "Marks lost" },
  { value: "confidence", label: "Confidence" },
  { value: "oldest", label: "Oldest" },
]
export function sortLabel(s: ReviewSort): string {
  return SORT_OPTIONS.find((o) => o.value === s)?.label ?? "Marks lost"
}

export function nextFocusAfter(ids: string[], decidedId: string): string | null {
  const at = ids.indexOf(decidedId)
  if (at === -1) return ids[0] ?? null
  return ids[at + 1] ?? ids[at - 1] ?? null
}

/** True while a menu or sheet is open, so the list shortcuts stay quiet behind it. */
export function overlayOpen(root: Pick<ParentNode, "querySelector">): boolean {
  return root.querySelector('[role="menu"], [role="dialog"]') !== null
}

/**
 * Put focus where the teacher is working after a decision: the next row, or the queue heading when
 * nothing is left. Returns false when the wanted row is not in the DOM yet, so the caller retries.
 */
export function focusAfterDecision(root: Pick<ParentNode, "querySelector">, nextId: string | null): boolean {
  const row = nextId ? root.querySelector<HTMLElement>(`[data-review-row="${nextId.replace(/["\\]/g, "\\$&")}"]`) : null
  const el = row ?? (nextId ? null : root.querySelector<HTMLElement>("[data-review-heading]"))
  if (!el) return false
  el.focus()
  return true
}
/**
 * When paging ends the Load more control unmounts, and a control that held focus drops it to the page body.
 * Put it back on the last open row (where the teacher was working, no scroll) or, with none, the column.
 * Only when focus really was on the control and is now lost: focus the teacher moved elsewhere stays.
 */
export function focusAfterPagingEnds(
  doc: { activeElement: unknown; body: unknown },
  column: (Pick<ParentNode, "querySelectorAll"> & { focus(options?: FocusOptions): void }) | null,
  hadFocus: boolean,
): boolean {
  if (!hadFocus || !column || doc.activeElement !== doc.body) return false
  const rows = column.querySelectorAll<HTMLElement>("[data-review-row]:not([data-gone])")
  const target = rows.length > 0 ? rows[rows.length - 1] : column
  target.focus({ preventScroll: true })
  return true
}

export function positionOf(ids: string[], id: string | null): { pos: number; total: number } {
  return { pos: id ? ids.indexOf(id) + 1 : 0, total: ids.length }
}

/** K10: the skip reasons, worded for a teacher. */
export const SKIP_LINE: Record<string, string> = {
  not_found: "no longer exists",
  forbidden: "outside your classes",
  already_closed: "already decided",
}

/*
 * All papers (S-09): every attempt in one subject, filterable, sortable, comparable.
 * Pure on purpose: the screen draws what this decides (state, filters, order, copy, links).
 */
import { ApiError } from "@/lib/api"
import type { PaperHistoryRow } from "@/lib/studentTypes"
import { gradeColorVar, links, plural, type TipView } from "../subject/subjectModel"

export type PeriodKey = "any" | "30d" | "90d" | "365d"
export type SortKey = "newest" | "oldest" | "highest" | "lowest"
export interface PapersFilters {
  paper: number | null
  variant: number | null
  session: string | null
  period: PeriodKey
  sort: SortKey
}
export const DEFAULT_FILTERS: PapersFilters = { paper: null, variant: null, session: null, period: "any", sort: "newest" }

export const PERIODS: { key: PeriodKey; label: string; days: number | null }[] = [
  { key: "any", label: "Any time", days: null },
  { key: "30d", label: "30 days", days: 30 },
  { key: "90d", label: "3 months", days: 90 },
  { key: "365d", label: "12 months", days: 365 },
]
export const SORTS: { key: SortKey; label: string }[] = [
  { key: "newest", label: "Newest" },
  { key: "oldest", label: "Oldest" },
  { key: "highest", label: "Highest" },
  { key: "lowest", label: "Lowest" },
]
const DAY_MS = 86_400_000

const enc = encodeURIComponent
export const papersLinks = {
  subject: (code: string) => `/student/subject/${enc(code)}`,
  self: links.papers,
} as const

/** Which of the data states the list is in; loading and error belong to the query wrapper. */
export type PapersMode = "empty" | "single" | "list"
export function papersMode(count: number): PapersMode {
  return count <= 0 ? "empty" : count === 1 ? "single" : "list"
}

/** The subject endpoint's two explicit "nothing here yet" answers: a first run, not a failure. */
export function isAbsentSubject(error: unknown, code: string): boolean {
  return (
    error instanceof ApiError &&
    error.status === 404 &&
    (error.detail === `No history for subject ${code}` || error.detail === `No papers for subject ${code}`)
  )
}

export function papersHeading(name: string, count: number): string {
  return `${name}, ${plural(count, "paper")}`
}
export function emptyTip(code: string, subjectName: string): TipView {
  return {
    mood: "open",
    line: "No papers yet",
    action: { label: `Scan a ${subjectName} paper`, detail: null, to: links.scan(code) },
    secondary: { label: "Upload a PDF instead", detail: null, to: links.upload(code) },
  }
}

/* ---- Filters ------------------------------------------------------------ */

const SESSION_ORDER: Record<string, number> = { "Feb/Mar": 1, "May/Jun": 2, "Oct/Nov": 3 }
/** Exam-session order, newest session first ("Oct/Nov 2024" before "May/Jun 2024"), not the order they were attempted in. A label that does not parse goes last. */
export function sortSessions(sessions: string[]): string[] {
  const key = (s: string) => {
    const [month, year] = [s.replace(/\s+\d{4}$/, ""), Number(s.match(/(\d{4})$/)?.[1])]
    return Number.isFinite(year) ? year * 10 + (SESSION_ORDER[month] ?? 0) : -1
  }
  return [...sessions].sort((a, b) => key(b) - key(a))
}

export interface FilterOptions { papers: number[]; variants: number[]; sessions: string[] }
/** A filter only has options when the data has more than one value for it: a one-choice filter filters nothing. */
export function filterOptions(history: PaperHistoryRow[]): FilterOptions {
  const papers = [...new Set(history.map((h) => h.paperNumber))].sort((a, b) => a - b)
  const variants = [...new Set(history.map((h) => h.variant))].sort((a, b) => a - b)
  const sessions = sortSessions([...new Set(history.map((h) => h.session))])
  const many = <T,>(xs: T[]) => (xs.length > 1 ? xs : [])
  return { papers: many(papers), variants: many(variants), sessions: many(sessions) }
}
export function activeFilterCount(f: PapersFilters): number {
  return [f.paper, f.variant, f.session].filter((v) => v !== null).length + (f.period !== "any" ? 1 : 0)
}

const percent = (h: PaperHistoryRow) => (h.maximum > 0 ? (h.awarded / h.maximum) * 100 : 0)
const time = (h: PaperHistoryRow) => new Date(h.recordedAt).getTime() || 0
const newerFirst = (a: PaperHistoryRow, b: PaperHistoryRow) => time(b) - time(a) || Number(b.id) - Number(a.id)

export function applyFilters(history: PaperHistoryRow[], f: PapersFilters, now: Date): PaperHistoryRow[] {
  const days = PERIODS.find((p) => p.key === f.period)?.days ?? null
  const since = days === null ? null : now.getTime() - days * DAY_MS
  const kept = history.filter(
    (h) =>
      (f.paper === null || h.paperNumber === f.paper) &&
      (f.variant === null || h.variant === f.variant) &&
      (f.session === null || h.session === f.session) &&
      (since === null || time(h) >= since),
  )
  const order: Record<SortKey, (a: PaperHistoryRow, b: PaperHistoryRow) => number> = {
    newest: newerFirst,
    oldest: (a, b) => newerFirst(b, a),
    highest: (a, b) => percent(b) - percent(a) || newerFirst(a, b),
    lowest: (a, b) => percent(a) - percent(b) || newerFirst(a, b),
  }
  return kept.sort(order[f.sort])
}

/** Filters and sort live in the address, so coming back from a result keeps them. Anything unknown falls to the default. */
export function parseFilters(params: URLSearchParams): PapersFilters {
  const whole = (key: string) => {
    const n = Number(params.get(key))
    return Number.isInteger(n) && n > 0 ? n : null
  }
  const period = params.get("when")
  const sort = params.get("sort")
  return {
    paper: whole("paper"),
    variant: whole("variant"),
    session: params.get("session") || null,
    period: PERIODS.some((p) => p.key === period) ? (period as PeriodKey) : "any",
    sort: SORTS.some((s) => s.key === sort) ? (sort as SortKey) : "newest",
  }
}
export function filtersToParams(f: PapersFilters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.paper !== null) p.set("paper", String(f.paper))
  if (f.variant !== null) p.set("variant", String(f.variant))
  if (f.session !== null) p.set("session", f.session)
  if (f.period !== "any") p.set("when", f.period)
  if (f.sort !== "newest") p.set("sort", f.sort)
  return p
}

/* ---- Filter trays ------------------------------------------------------- */

/**
 * Whether a choice tray has more past its end: the cue to fade that edge. Reads `Math.abs(scrollLeft)` because the tray
 * scrolls negatively in right-to-left. A tray in a `display: none` panel has no box (both widths 0), so it reports false
 * until the panel shows; whoever measures must measure again then.
 */
export function trayHasMore(tray: { scrollWidth: number; clientWidth: number; scrollLeft: number }): boolean {
  return tray.scrollWidth - tray.clientWidth - Math.abs(tray.scrollLeft) > 1
}

/* ---- Rows --------------------------------------------------------------- */

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" })
export function dayLabel(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? "" : DAY.format(d)
}
/**
 * How sure the marker was, in the result screen's tiers (a self-mark or a teacher's accept settles a question, a flagged one
 * is its own "needs review"). Silent when the store kept no per-question evidence: no evidence is not the same claim as "all sure".
 */
export function confidenceLine(c: PaperHistoryRow["confidence"]): string | null {
  if (!c || c.scored <= 0) return null
  const { scored, uncertain, needsReview } = c
  const review = `${needsReview} ${needsReview === 1 ? "needs" : "need"} review`
  if (uncertain === 0 && needsReview === 0) return `All ${scored} sure`
  if (needsReview === 0) return `${uncertain} of ${scored} unsure`
  if (uncertain === 0) return `${needsReview} of ${scored} ${needsReview === 1 ? "needs" : "need"} review`
  return `${uncertain} of ${scored} unsure, ${review}`
}
export interface PaperRowView {
  id: string
  grade: string
  colorVar: string
  title: string
  marks: string
  pct: string
  date: string
  confidence: string | null
  corrected: string | null
  to: string
}
export function rowViews(history: PaperHistoryRow[], _now: Date): PaperRowView[] {
  return history.map((h) => ({
    id: h.id,
    grade: h.grade,
    colorVar: gradeColorVar(h.grade),
    title: h.label,
    marks: `${h.awarded}/${h.maximum}`,
    pct: `${Math.round(percent(h))}%`,
    date: dayLabel(h.recordedAt),
    confidence: confidenceLine(h.confidence),
    corrected: h.teacherCorrected > 0 ? `Teacher re-marked ${plural(h.teacherCorrected, "question")}` : null,
    to: links.result(h.id),
  }))
}

/* ---- Compare ------------------------------------------------------------ */

/** A pick toggles; two are held; a third replaces the oldest pick. */
export function toggleSelected(selected: string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter((s) => s !== id)
  return selected.length < 2 ? [...selected, id] : [selected[1], id]
}
/** A pick the filters now hide is dropped: it would sit in the compare panel with no row to show it. */
export function prunePicks(picks: string[], visible: PaperHistoryRow[]): string[] {
  return picks.filter((id) => visible.some((h) => h.id === id))
}
export interface CompareSide {
  id: string
  title: string
  grade: string
  colorVar: string
  marks: string
  pct: string
  date: string
  to: string
}
export interface CompareView { earlier: CompareSide; later: CompareSide; change: string; grades: string }
const side = (h: PaperHistoryRow): CompareSide => ({
  id: h.id,
  title: h.label,
  grade: h.grade,
  colorVar: gradeColorVar(h.grade),
  marks: `${h.awarded}/${h.maximum}`,
  pct: `${Math.round(percent(h))}%`,
  date: dayLabel(h.recordedAt),
  to: links.result(h.id),
})
/** Null until two picks that still exist are made. The change is plain words, never coloured by its sign. */
export function compareView(history: PaperHistoryRow[], selected: string[], _now: Date): CompareView | null {
  if (selected.length !== 2) return null
  const picked = selected.map((id) => history.find((h) => h.id === id))
  if (picked.some((h) => !h)) return null
  const [earlier, later] = (picked as PaperHistoryRow[]).sort((a, b) => newerFirst(b, a))
  const diff = Math.round(percent(later)) - Math.round(percent(earlier))
  return {
    earlier: side(earlier),
    later: side(later),
    change: diff === 0 ? "No change" : `${diff > 0 ? "Up" : "Down"} ${plural(Math.abs(diff), "point")}`,
    grades: earlier.grade === later.grade ? `Both ${later.grade}` : `${earlier.grade} to ${later.grade}`,
  }
}

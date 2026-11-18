/* Pure subject-screen decisions; the caller supplies the clock. */
import type { BinnyMood, TopicState, Grade } from "@/components/redesign"
import { daysUntil } from "@/components/redesign"
import type { StudentExamCalendar } from "@/lib/announcementTypes"
import type { DeckSummaryDTO } from "@/lib/flashcardTypes"
import { gradeTone } from "@/lib/grade"
import type { CatalogueSubject } from "@/lib/referenceTypes"
import type { PaperBreakdown, PaperHistoryRow, Subject, TopicTile, GoalLine } from "@/lib/studentTypes"

export type SubjectScreenState = "loading" | "error" | "first-run" | "sparse" | "full"
export interface QueryFacts {
  status: "pending" | "error" | "success"
  errorStatus: number | null
  paperCount: number
}
export function selectScreenState(q: QueryFacts): SubjectScreenState {
  if (q.status === "pending") return "loading"
  if (q.status === "error") return q.errorStatus === 404 ? "first-run" : "error"
  return q.paperCount === 0 ? "first-run" : q.paperCount === 1 ? "sparse" : "full"
}
const enc = encodeURIComponent
export const links = {
  scan: (code: string) => `/student/correct?subject=${enc(code)}`,
  upload: (code: string) => `/student/correct?subject=${enc(code)}&source=file`,
  practice: (code: string, topic?: string) => `/student/practice/${enc(code)}${topic ? `?topic=${enc(topic)}` : ""}`,
  flashcards: (code: string, deckId: string) => `/student/flashcards/${enc(code)}?deck=${enc(deckId)}`,
  plan: (code: string) => `/student/plan/${enc(code)}`,
  result: (id: string) => `/student/result/${enc(id)}`,
  home: "/student",
} as const
export function gradeColorVar(grade: Grade): string { return `var(--grade-${gradeTone(grade) ?? "u"})` }
export function gradeArticle(grade: string): "a" | "an" { return /^[AEF8]/i.test(grade.trim()) ? "an" : "a" }
export function plural(n: number, word: string): string { return `${n} ${word}${n === 1 ? "" : "s"}` }
const MONTH = new Intl.DateTimeFormat("en-US", { month: "short" })
export function monthLabel(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? "" : MONTH.format(date)
}
export function monthYearLabel(iso: string, now: Date): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ""
  return date.getFullYear() === now.getFullYear() ? MONTH.format(date) : `${MONTH.format(date)} ${date.getFullYear()}`
}
export function topicName(topic: string): string {
  return /^([A-Z]{0,2}\d+(?:\.\d+)*[a-z]?)\s+(.+)$/.exec(topic.trim())?.[2] ?? topic.trim()
}
export const STEP_WINDOW = 4
export const SPARSE_GHOSTS = 3
export function barHeight(marks: number, outOf: number, line: number): number {
  const floor = outOf * 0.4
  return line <= floor ? 100 : Math.min(100, Math.max(0, Math.round((marks - floor) / (line - floor) * 100)))
}
export interface StepBar {
  id: string; grade: string; marks: number; outOf: number; month: string; heightPct: number
  current: boolean; colorVar: string; ariaLabel: string; resultTo: string
}
export interface GoalStep {
  grade: string; marks: number; outOf: number; gap: number; gapLabel: string; sourceLabel: string; ariaLabel: string
}
export interface StepsView { bars: StepBar[]; ghosts: number; goal: GoalStep | null; groupLabel: string }
function boundaryGoal(paper: PaperBreakdown): GoalLine | null {
  if (paper.goal) return paper.goal
  const match = /^(.+?)\s+line\s+(\d+)\/(\d+)$/i.exec(paper.boundary.trim())
  if (!match || Number(match[3]) <= 0) return null
  return { grade: match[1], marks: Number(match[2]), outOf: Number(match[3]), source: "global_default", sourceLabel: "" }
}
export function stepsFor(paper: PaperBreakdown, { ghosts = 0 }: { ghosts?: number } = {}): StepsView {
  const shown = paper.attempts.slice(-STEP_WINDOW)
  const latest = paper.attempts.at(-1)
  const boundary = boundaryGoal(paper)
  const bars = shown.map((a, i): StepBar => {
    const month = monthLabel(a.recordedAt)
    const line = boundary ? boundary.marks / boundary.outOf * a.maximum : a.maximum
    return { id: a.id, grade: a.grade, marks: a.awarded, outOf: a.maximum, month,
      heightPct: barHeight(a.awarded, a.maximum, line), current: i === shown.length - 1,
      colorVar: gradeColorVar(a.grade), ariaLabel: `${a.grade}, ${a.awarded} out of ${a.maximum}${month ? `, ${month}` : ""}. Open this paper`, resultTo: links.result(a.id) }
  })
  let goal: GoalStep | null = null
  if (boundary && latest) {
    const gap = boundary.marks - latest.awarded
    goal = { grade: boundary.grade, marks: boundary.marks, outOf: boundary.outOf, gap,
      gapLabel: gap > 0 ? `${gap} to go` : "Reached", sourceLabel: boundary.sourceLabel,
      ariaLabel: `${boundary.grade} line, ${boundary.marks} out of ${boundary.outOf}. ${gap > 0 ? `${plural(gap, "mark")} to go` : "Reached"}` }
  }
  const summary = bars.map(b => `${b.grade}, ${b.marks} out of ${b.outOf}${b.month ? ` in ${b.month}` : ""}`).join("; ")
  const goalText = goal ? ` The ${goal.grade} line is ${goal.marks}, ${goal.gap > 0 ? `${plural(goal.gap, "mark")} to go` : "reached"}.` : ""
  return { bars, ghosts, goal, groupLabel: summary ? `Paper ${paper.paperNumber} marks so far: ${summary}.${goalText}` : `Paper ${paper.paperNumber}: no marks yet.` }
}
export type TrendView = { kind: "trend"; forecast: string; article: "a" | "an"; colorVar: string; change: string } | { kind: "single"; text: string }
export function trendFor(paper: PaperBreakdown, forecast: string, subjectPaperCount: number): TrendView {
  const a = paper.attempts
  if (a.length < 2) return { kind: "single", text: subjectPaperCount <= 1 ? "One step so far. Two more papers show your trend." : `One Paper ${paper.paperNumber} so far.` }
  const first = a[0], last = a[a.length - 1]
  const diff = last.awarded - (first.maximum > 0 ? Math.round(first.awarded / first.maximum * last.maximum) : first.awarded)
  const since = monthLabel(first.recordedAt) || "your first paper"
  const change = diff > 0 ? `up ${plural(diff, "mark")} since ${since}` : diff < 0 ? `down ${plural(-diff, "mark")} since ${since}` : `level since ${since}`
  return { kind: "trend", forecast, article: gradeArticle(forecast), colorVar: gradeColorVar(forecast), change }
}
export interface PaperTab { paperNumber: number; name: string }
export function paperTabs(papers: PaperBreakdown[]): PaperTab[] {
  return papers.filter(p => p.attempts.length > 0).sort((a, b) => b.paperNumber - a.paperNumber).map(p => ({ paperNumber: p.paperNumber, name: `Paper ${p.paperNumber}` }))
}
export function defaultPaper(papers: PaperBreakdown[]): number | null {
  let best: { n: number; t: number } | null = null
  for (const p of papers) {
    const last = p.attempts.at(-1)
    if (!last) continue
    const t = Date.parse(last.recordedAt)
    if (!best || t > best.t || (Number.isNaN(best.t) && !Number.isNaN(t))) best = { n: p.paperNumber, t }
  }
  return best?.n ?? null
}
export function resolvePaper(papers: PaperBreakdown[], requested: string | null): number | null {
  const n = Number(requested)
  return requested !== null && /^\d+$/.test(requested) && papers.some(p => p.paperNumber === n && p.attempts.length > 0) ? n : defaultPaper(papers)
}
export interface PaperRowView { id: string; grade: string; colorVar: string; title: string; sub: string; to: string }
export function paperRows(history: PaperHistoryRow[], now: Date): PaperRowView[] {
  return history.map(h => ({ id: h.id, grade: h.grade, colorVar: gradeColorVar(h.grade), title: h.label,
    sub: [`${h.awarded}/${h.maximum}`, monthYearLabel(h.recordedAt, now)].filter(Boolean).join(" · "), to: links.result(h.id) }))
}
export function visiblePapers(count: number, wide: boolean, expanded: boolean): number { return expanded ? count : Math.min(count, wide ? 5 : 4) }
export function tierLabel(subject: CatalogueSubject | undefined, paperNumber: number | null): string | null {
  const tier = subject?.papers.find(p => p.number === paperNumber)?.tier
  return tier ? tier.charAt(0).toUpperCase() + tier.slice(1) : null
}
export function subtitleFor(secondary: string, tier: string | null): string { return [secondary, tier].filter(Boolean).join(" · ") }
export const NEAR_EXAM_DAYS = 30
export function nextExamDate(calendar: StudentExamCalendar | undefined, code: string, now: Date): string | null {
  return calendar?.entries.filter(e => e.subjectCode === code && e.availability === "dated")
    .flatMap(e => e.dates.map(d => d.examDate)).filter(d => daysUntil(d, now) >= 0).sort()[0] ?? null
}
export type { BinnyMood, DeckSummaryDTO, Subject, TopicState, TopicTile }

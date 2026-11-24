/* Pure subject-screen decisions; the caller supplies the clock. */
import type { BinnyMood, TopicState, Grade } from "@/components/redesign"
import { daysUntil } from "@/components/redesign"
import type { StudentExamCalendar } from "@/lib/announcementTypes"
import type { DeckSummaryDTO } from "@/lib/flashcardTypes"
import { gradeTone } from "@/lib/grade"
import type { CatalogueSubject } from "@/lib/referenceTypes"
import type { PaperBreakdown, PaperHistoryRow, Subject, TopicTile } from "@/lib/studentTypes"

export type SubjectScreenState = "loading" | "error" | "first-run" | "sparse" | "full"
export interface QueryFacts {
  status: "pending" | "error" | "success"
  errorStatus: number | null
  paperCount: number
  /** `data !== undefined`. react-query v5 reports status "error" for a failed refetch yet keeps the last good data. */
  hasData: boolean
}
/** A failed first load is an error screen. A failed refetch over data already loaded keeps that screen. */
export function selectScreenState(q: QueryFacts): SubjectScreenState {
  if (q.status === "pending") return "loading"
  if (q.status === "error" && !q.hasData) return q.errorStatus === 404 ? "first-run" : "error"
  return q.paperCount === 0 ? "first-run" : q.paperCount === 1 ? "sparse" : "full"
}
/** The body is still showing but its refresh failed: the screen adds a quiet notice. */
export function refreshFailed(q: QueryFacts): boolean { return q.status === "error" && q.hasData }
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
export function stepsFor(paper: PaperBreakdown, { ghosts = 0 }: { ghosts?: number } = {}): StepsView {
  const shown = paper.attempts.slice(-STEP_WINDOW)
  const latest = paper.attempts.at(-1)
  const goalLine = paper.goal
  const bars = shown.map((a, i): StepBar => {
    const month = monthLabel(a.recordedAt)
    const line = goalLine ? goalLine.marks / goalLine.outOf * a.maximum : a.maximum
    return { id: a.id, grade: a.grade, marks: a.awarded, outOf: a.maximum, month,
      heightPct: barHeight(a.awarded, a.maximum, line), current: i === shown.length - 1,
      colorVar: gradeColorVar(a.grade), ariaLabel: `${a.grade}, ${a.awarded} out of ${a.maximum}${month ? `, ${month}` : ""}. Open this paper`, resultTo: links.result(a.id) }
  })
  let goal: GoalStep | null = null
  if (goalLine && latest) {
    const gap = goalLine.marks - latest.awarded
    goal = { grade: goalLine.grade, marks: goalLine.marks, outOf: goalLine.outOf, gap,
      gapLabel: gap > 0 ? `${gap} to go` : "Reached", sourceLabel: goalLine.sourceLabel,
      ariaLabel: `${goalLine.grade} line, ${goalLine.marks} out of ${goalLine.outOf}. ${gap > 0 ? `${plural(gap, "mark")} to go` : "Reached"}` }
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
export interface TipAction { label: string; detail: string | null; to: string }
export interface TipView { mood: BinnyMood; line: string; action: TipAction; secondary: TipAction | null }

export function rankedWins(topics: TopicTile[]): TopicTile[] {
  return topics.filter(t => t.marksToWin > 0)
    .sort((a, b) => b.marksToWin - a.marksToWin || a.accuracy - b.accuracy || a.name.localeCompare(b.name))
}
export function fullTipLine(goal: GoalStep | null, examInDays: number | null): string {
  if (!goal) return "Next paper?"
  const { gap, grade } = goal
  if (gap > 0 && examInDays !== null && examInDays >= 0 && examInDays <= NEAR_EXAM_DAYS) {
    return examInDays === 0 ? "Exam today" : `${plural(examInDays, "day")}, ${plural(gap, "mark")}`
  }
  if (gap > 0) return `${plural(gap, "mark")} to ${grade}`
  return gap === 0 ? `On the ${grade} line` : `Above the ${grade} line`
}
const scanAction = (code: string): TipAction => ({ label: "Scan your next paper", detail: null, to: links.scan(code) })
export function fullTip(code: string, goal: GoalStep | null, topics: TopicTile[], examInDays: number | null): TipView {
  const top = rankedWins(topics)[0]
  return { mood: "happy", line: fullTipLine(goal, examInDays), action: top
    ? { label: `Practise ${topicName(top.name)}`, detail: `+${plural(top.marksToWin, "mark")}`, to: links.practice(code, top.name) }
    : scanAction(code), secondary: null }
}
export function sparseTip(code: string): TipView {
  return { mood: "happy", line: "Great start. Next paper?", action: scanAction(code), secondary: null }
}
export function firstRunTip(code: string, subjectName: string): TipView {
  return { mood: "open", line: "Find your first step",
    action: { label: `Scan a ${subjectName} paper`, detail: null, to: links.scan(code) },
    secondary: { label: "Upload a PDF instead", detail: null, to: links.upload(code) } }
}
export function FIRST_RUN_STEPS(subjectName: string): { title: string; body: string }[] {
  return [
    { title: `Scan a ${subjectName} paper`, body: "Any past paper you have tried. Phone camera or PDF." },
    { title: "Lemely marks it", body: "Every question, with method marks. About two minutes." },
    { title: "Your path appears", body: "Each paper adds a step towards your goal." },
  ]
}
export const GHOST_PATH_HEIGHTS = [30, 45, 52, 70] as const
export const GHOST_CHIPS: { state: TopicState; width: number }[] = [
  { state: "work", width: 96 }, { state: "getting", width: 120 }, { state: "secure", width: 88 },
  { state: "getting", width: 140 }, { state: "secure", width: 104 }, { state: "work", width: 92 },
  { state: "secure", width: 128 }, { state: "getting", width: 110 },
]

export interface WinRowView { topic: string; name: string; marks: number; practiceTo: string; flashcardsTo: string | null }
export interface WinView { heading: string; rows: WinRowView[] }
export function winRows(code: string, topics: TopicTile[], decks: DeckSummaryDTO[], mode: "full" | "sparse"): WinView {
  const ranked = rankedWins(topics)
  const picked = mode === "full" ? ranked.slice(1, 4) : ranked.slice(0, 2)
  return { heading: mode === "full" ? "More marks to win" : "Marks to win", rows: picked.map(t => {
    const deck = decks.find(d => d.subjectCode === code && d.topic === t.name)
    return { topic: t.name, name: topicName(t.name), marks: t.marksToWin, practiceTo: links.practice(code, t.name),
      flashcardsTo: deck ? links.flashcards(code, deck.id) : null }
  }) }
}
export const SECURE_AT = 75
export const GETTING_AT = 60
export function topicState(accuracy: number): TopicState {
  return accuracy >= SECURE_AT ? "secure" : accuracy >= GETTING_AT ? "getting" : "work"
}
export interface TopicChipView { topic: string; label: string; state: TopicState; pct: number }
export function topicChips(topics: TopicTile[]): TopicChipView[] {
  return [...topics].sort((a, b) => a.accuracy - b.accuracy || a.name.localeCompare(b.name))
    .map(t => ({ topic: t.name, label: topicName(t.name), state: topicState(t.accuracy), pct: t.accuracy }))
}
export function topicsHint(mode: "full" | "sparse", shown: number, total: number | null): string | null {
  if (shown === 0) return "Topics show up once a paper loses a mark."
  if (mode === "full") return null
  if (total !== null && shown < total) return `${shown} of ${total} topics so far. Each paper fills in more.`
  return "Each paper fills in more topics."
}
export interface PathView { tabs: PaperTab[]; selected: number; goalGrade: string | null; steps: StepsView; trend: TrendView }
export interface SubjectView {
  mode: "full" | "sparse"; path: PathView; tip: TipView; win: WinView; chips: TopicChipView[]
  topicsHint: string | null; papers: PaperRowView[]
}
export interface SubjectViewInput {
  data: Subject; catalogue: CatalogueSubject | undefined; decks: DeckSummaryDTO[]; examDate: string | null
  now: Date; requestedPaper: string | null; mode: "full" | "sparse"
}
/** Null when no paper has an attempt: that is the first-run screen, which has no path to build. */
export function buildSubjectView(input: SubjectViewInput): SubjectView | null {
  const { data, catalogue, decks, examDate, now, requestedPaper, mode } = input
  const code = data.header.code
  const papers = data.papersBreakdown.filter(p => p.attempts.length > 0)
  if (papers.length === 0) return null
  const selected = resolvePaper(papers, requestedPaper)
  const paper = papers.find(p => p.paperNumber === selected) ?? papers[0]
  const steps = stepsFor(paper, { ghosts: mode === "sparse" ? SPARSE_GHOSTS : 0 })
  const examInDays = examDate ? daysUntil(examDate, now) : null
  const chips = topicChips(data.topicMap)
  return { mode, path: { tabs: paperTabs(papers), selected: paper.paperNumber, goalGrade: steps.goal?.grade ?? null,
    steps, trend: trendFor(paper, data.header.forecast, data.paperHistory.length) },
  tip: mode === "full" ? fullTip(code, steps.goal, data.topicMap, examInDays) : sparseTip(code),
  win: winRows(code, data.topicMap, decks, mode), chips,
  topicsHint: topicsHint(mode, chips.length, catalogue ? catalogue.topics.length : null), papers: paperRows(data.paperHistory, now) }
}
export type { BinnyMood, DeckSummaryDTO, Subject, TopicState, TopicTile }

/**
 * How far the tray has to scroll for the chosen tab to sit fully inside it: 0 when it already does, else the gap on
 * the side it overhangs. Works from on-screen rectangles, so it is the same in left-to-right and right-to-left.
 */
export function scrollDeltaToReveal(tray: { left: number; right: number }, tab: { left: number; right: number }): number {
  if (tab.right > tray.right) return tab.right - tray.right
  if (tab.left < tray.left) return tab.left - tray.left
  return 0
}

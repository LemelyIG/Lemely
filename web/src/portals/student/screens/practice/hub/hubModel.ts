/*
 * Practice tab (L4) view model. Pure: no React, no DOM, no `.tsx` imports.
 * Every decision the hub screen makes lives here: the state, the subtitle,
 * Binny's mood and line, the tile statuses, the homework row, win marks back
 * and Recent. The screen only renders `HubView`.
 */
import type { PracticeRun, StudentQuizListItem } from "@/lib/practiceHubTypes"
import type { PracticeTopics } from "@/lib/practiceTypes"
import { plural, topicLabel } from "../practiceCopy"

export type HubQueryStatus = "pending" | "error" | "success"
export type HubState = "loading" | "error" | "firstTime" | "sparse" | "normal"

export interface HubSubject {
  code: string
  name: string
  /** Marked papers in this subject (OverviewDTO `subjects[].papers`); 0 for an enrolment with none. */
  papers: number
}

export interface HubInput {
  overviewStatus: HubQueryStatus
  subjects: readonly HubSubject[]
  topics: readonly { code: string; status: HubQueryStatus; data?: PracticeTopics }[]
  runsStatus: HubQueryStatus
  runs: readonly PracticeRun[]
  /** Empty when the list failed: the row simply hides. */
  homework: readonly StudentQuizListItem[]
  /** null when unknown (loading or failed). */
  dueTotal: number | null
  deckCount: number | null
  /** One entry per subject, in subject order. `available` null while loading. */
  placement: readonly { code: string; available: boolean | null; minutes: number | null }[]
  now: Date
}

export type TileKey = "set" | "cards" | "paper" | "test"
export type HubTileTone = "tide" | "violet" | "mint" | "gold"

export interface TileView {
  key: TileKey
  title: string
  status: string
  tone: HubTileTone
  to: string | null
  disabled: boolean
  /** The flashcards due count, rendered in Mono inside the ReactNode status; null otherwise. */
  count: number | null
}

export interface WinBackRow {
  topic: string
  label: string
  subjectCode: string
  subjectName: string
  marks: number
  to: string
}

export interface HomeworkView {
  assignmentId: string
  title: string
  sub: string
  to: string
}

export type RecentKind = "resume" | "marking" | "done"

export interface RecentRow {
  assignmentId: string
  kind: RecentKind
  title: string
  subjectCode: string
  subjectName: string
  sub: string
  to: string
}

export interface HubView {
  state: HubState
  subtitle: string | null
  binny: { mood: "happy" | "open"; line: string } | null
  homework: HomeworkView | null
  tiles: TileView[]
  winBack: WinBackRow[]
  allTopicsTo: string | null
  recent: RecentRow[]
  recentMore: RecentRow[]
  showScanTip: boolean
  primarySubject: string | null
}

export const RECENT_SHOWN = 4
export const WIN_BACK_SHOWN = 3

const DAY_MS = 86_400_000
const UNFINISHED = new Set(["not_started", "in_progress"])

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function dayDiff(isoString: string, now: Date): number {
  return Math.round((startOfDay(new Date(isoString)) - startOfDay(now)) / DAY_MS)
}

function shortDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString("en-GB", { day: "numeric", month: "short" })
}

/** "Today", "Yesterday", "Tue" within the week, else "2 Nov". */
export function dayLabel(isoString: string, now: Date): string {
  const diff = dayDiff(isoString, now)
  if (diff === 0) return "Today"
  if (diff === -1) return "Yesterday"
  if (diff < -1 && diff > -7) return new Date(isoString).toLocaleDateString("en-GB", { weekday: "short" })
  return shortDate(isoString)
}

export function dueLabel(item: Pick<StudentQuizListItem, "dueAt" | "isOverdue">, now: Date): string | null {
  if (item.isOverdue) return "overdue"
  if (!item.dueAt) return null
  const diff = dayDiff(item.dueAt, now)
  if (diff <= 0) return "due today"
  if (diff === 1) return "due tomorrow"
  if (diff < 7) return `due ${new Date(item.dueAt).toLocaleDateString("en-GB", { weekday: "long" })}`
  return `due ${shortDate(item.dueAt)}`
}

export function hubState(input: HubInput): HubState {
  const anyError =
    input.overviewStatus === "error" || input.runsStatus === "error" || input.topics.some((t) => t.status === "error")
  if (anyError) return "error"
  const anyPending =
    input.overviewStatus === "pending" || input.runsStatus === "pending" || input.topics.some((t) => t.status === "pending")
  if (anyPending) return "loading"
  const papers = input.subjects.reduce((sum, s) => sum + s.papers, 0)
  if (papers === 0 && input.runs.length === 0) return "firstTime"
  if (papers === 1) return "sparse"
  return "normal"
}

function namesOf(subjects: readonly HubSubject[]): Map<string, string> {
  return new Map(subjects.map((s) => [s.code, s.name]))
}

export function winBackRows(subjects: readonly HubSubject[], topics: HubInput["topics"]): WinBackRow[] {
  const names = namesOf(subjects)
  const rows: WinBackRow[] = []
  for (const entry of topics) {
    if (!entry.data) continue
    for (const t of entry.data.topics) {
      if (t.marksLost <= 0) continue
      rows.push({
        topic: t.topic,
        label: topicLabel(t.topic),
        subjectCode: entry.code,
        subjectName: names.get(entry.code) ?? entry.code,
        marks: t.marksLost,
        to: `/student/practice/${entry.code}?topic=${encodeURIComponent(t.topic)}`,
      })
    }
  }
  return rows.sort((a, b) => b.marks - a.marks || a.label.localeCompare(b.label))
}

export function recentRows(runs: readonly PracticeRun[], subjects: readonly HubSubject[], now: Date): RecentRow[] {
  const names = namesOf(subjects)
  const byRecency = (a: PracticeRun, b: PracticeRun) => Date.parse(b.lastActivityAt) - Date.parse(a.lastActivityAt)
  const ordered = [
    ...runs.filter((r) => UNFINISHED.has(r.status)).sort(byRecency),
    ...runs.filter((r) => !UNFINISHED.has(r.status)).sort(byRecency),
  ]
  return ordered.map((r): RecentRow => {
    const base = {
      assignmentId: r.assignmentId,
      title: r.topics.length > 0 ? topicLabel(r.topics[0]) : r.title,
      subjectCode: r.subjectCode,
      subjectName: names.get(r.subjectCode) ?? r.subjectCode,
    }
    if (UNFINISHED.has(r.status)) {
      const next = Math.min(r.answeredCount + 1, Math.max(r.questionCount, 1))
      return { ...base, kind: "resume", sub: `Question ${next} of ${r.questionCount} · saved`, to: `/student/practice/set/${r.assignmentId}` }
    }
    const day = dayLabel(r.lastActivityAt, now)
    if (r.status === "marked" && r.awardedMarks !== null && r.maximumMarks !== null) {
      return { ...base, kind: "done", sub: `${r.awardedMarks} of ${r.maximumMarks} back · ${day}`, to: `/student/practice/result/${r.assignmentId}` }
    }
    return { ...base, kind: "marking", sub: `Marking · ${day}`, to: `/student/practice/result/${r.assignmentId}` }
  })
}

export function pickHomework(list: readonly StudentQuizListItem[], now: Date): HomeworkView | null {
  const open = list.filter((q) => q.teacherName !== null && q.isOpen && UNFINISHED.has(q.submissionStatus))
  if (open.length === 0) return null
  const sorted = [...open].sort((a, b) => {
    if (a.isOverdue !== b.isOverdue) return a.isOverdue ? -1 : 1
    const ad = a.dueAt ? Date.parse(a.dueAt) : Number.POSITIVE_INFINITY
    const bd = b.dueAt ? Date.parse(b.dueAt) : Number.POSITIVE_INFINITY
    if (ad !== bd) return ad - bd
    return Date.parse(b.assignedAt) - Date.parse(a.assignedAt)
  })
  const first = sorted[0]
  const parts = [first.teacherName as string, plural(first.questionCount, "question")]
  const due = dueLabel(first, now)
  if (due) parts.push(due)
  if (sorted.length > 1) parts.push(`+${sorted.length - 1} more`)
  return {
    assignmentId: first.assignmentId,
    title: `Homework · ${first.quizTitle}`,
    sub: parts.join(" · "),
    to: `/student/practice/set/${first.assignmentId}`,
  }
}

function cardsStatus(due: number | null, decks: number | null): string {
  if (due !== null && due > 0) return `${due} due today`
  if (decks === 0) return "Make your first deck"
  if (due === 0) return "All caught up"
  return "Review your cards"
}

export function hubTiles(input: {
  firstTime: boolean
  primarySubject: string | null
  dueTotal: number | null
  deckCount: number | null
  placement: HubInput["placement"]
}): TileView[] {
  const primary = input.primarySubject
  const available = input.placement.find((p) => p.available === true)
  const noneAvailable = input.placement.length > 0 && input.placement.every((p) => p.available === false)
  const testTo = available
    ? `/student/placement/${available.code}`
    : noneAvailable || primary === null
      ? null
      : `/student/placement/${primary}`
  return [
    {
      key: "set",
      title: "Practice set",
      status: input.firstTime ? "Pick any topic" : "Build your own",
      tone: "tide",
      to: primary ? `/student/practice/${primary}` : null,
      disabled: primary === null,
      count: null,
    },
    {
      key: "cards",
      title: "Flashcards",
      status: cardsStatus(input.dueTotal, input.deckCount),
      tone: "violet",
      to: "/student/flashcards",
      disabled: false,
      count: input.dueTotal !== null && input.dueTotal > 0 ? input.dueTotal : null,
    },
    { key: "paper", title: "Past papers", status: "Print or do timed", tone: "mint", to: "/student/practice/papers", disabled: false, count: null },
    {
      key: "test",
      title: "Placement test",
      status: available
        ? available.minutes
          ? `Find your level · ${available.minutes} min`
          : "Find your level"
        : noneAvailable
          ? "Not ready yet"
          : "Find your level",
      tone: "gold",
      to: testTo,
      disabled: testTo === null,
      count: null,
    },
  ]
}

function binnyFor(state: HubState, top: WinBackRow | undefined): HubView["binny"] {
  if (state === "firstTime") return { mood: "open", line: "Scan a paper and I'll find your marks to win back." }
  if (state === "sparse") return { mood: "happy", line: "Good start. Try one set." }
  if (state === "normal") {
    return top
      ? { mood: "happy", line: `${top.label} first. +${top.marks} marks.` }
      : { mood: "happy", line: "All caught up. Try a set." }
  }
  return null
}

export function practiceHubView(input: HubInput): HubView {
  const state = hubState(input)
  const allWinBack = winBackRows(input.subjects, input.topics)
  const primarySubject = allWinBack[0]?.subjectCode ?? input.subjects[0]?.code ?? null
  const recentAll = recentRows(input.runs, input.subjects, input.now)
  const showsContent = state === "normal" || state === "sparse"
  return {
    state,
    subtitle: showsContent && allWinBack.length > 0 ? `${plural(allWinBack.length, "topic")} to win back` : null,
    binny: binnyFor(state, allWinBack[0]),
    homework: state === "loading" ? null : pickHomework(input.homework, input.now),
    tiles: hubTiles({
      firstTime: state === "firstTime",
      primarySubject,
      dueTotal: input.dueTotal,
      deckCount: input.deckCount,
      placement: input.placement,
    }),
    winBack: showsContent ? allWinBack.slice(0, WIN_BACK_SHOWN) : [],
    allTopicsTo:
      showsContent && allWinBack.length > WIN_BACK_SHOWN ? `/student/subject/${allWinBack[0].subjectCode}` : null,
    recent: showsContent ? recentAll.slice(0, RECENT_SHOWN) : [],
    recentMore: showsContent ? recentAll.slice(RECENT_SHOWN) : [],
    showScanTip: state === "sparse",
    primarySubject,
  }
}

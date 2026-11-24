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
export type HubErrorKind = "topics" | "subjects"

/**
 * Maps the profile query onto a hub status. Cached data always reads as
 * success. With none, an uncached manual retry resets TanStack's status from
 * error to pending but keeps `errorUpdateCount`, so the failure stays an error
 * until the retry lands and the Retry button does not unmount mid-flight.
 */
export function profileQueryState(query: { data: unknown; status: HubQueryStatus; errorUpdateCount: number; isFetching: boolean }): { profileStatus: HubQueryStatus; refetching: boolean } {
  const profileStatus = query.data !== undefined ? "success"
    : query.status === "pending" && query.errorUpdateCount > 0 ? "error" : query.status
  return { profileStatus, refetching: query.isFetching }
}

export interface HubSubject {
  code: string
  name: string
  /** Marked papers in this subject (OverviewDTO `subjects[].papers`); 0 for an enrolment with none. */
  papers: number
}

export interface HubInput {
  overviewStatus: HubQueryStatus
  profileStatus: HubQueryStatus
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
export type HubTileTone = "tide" | "violet" | "mint" | "sea"

export interface TileView {
  key: TileKey
  title: string
  status: string
  tone: HubTileTone
  to: string | null
  disabled: boolean
  /** The tile opens the builder sheet over the hub (a button that pushes the route), not a page (a link). */
  opensSheet: boolean
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
  /** Set exactly when `state` is "error": which source failed, so the copy only promises what still works. */
  errorKind: HubErrorKind | null
  /** The lists render but the profile failed, so subjects with no paper yet may be missing. */
  notice: "subjects" | null
  subtitle: string | null
  binny: { mood: "happy" | "open"; line: string } | null
  homework: HomeworkView | null
  tiles: TileView[]
  winBack: WinBackRow[]
  winBackMore: WinBackRow[]
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

function isPending(input: HubInput): boolean {
  return input.overviewStatus === "pending" || input.profileStatus === "pending" || input.runsStatus === "pending" || input.topics.some((t) => t.status === "pending")
}

/**
 * Why the hub cannot render its lists, or null when it can.
 * - "topics": overview, runs or a subject's topics failed with nothing cached.
 * - "subjects": only the profile failed, and no other source gave a subject to
 *   work from. The profile is what finds enrolled subjects that have no paper
 *   yet, so without it the hub cannot tell a first run from a failed load.
 * A failed profile alongside subjects the overview already gave is not an
 * error: the lists render and `practiceHubView` raises a notice instead.
 */
function failureKind(input: HubInput): HubErrorKind | null {
  const topicsFailed =
    input.overviewStatus === "error" || input.runsStatus === "error" || input.topics.some((t) => t.status === "error" && t.data === undefined)
  if (topicsFailed) return "topics"
  // A pending source may still bring subjects, so never call the profile fatal while one loads.
  if (isPending(input)) return null
  if (input.profileStatus === "error" && input.subjects.length === 0) return "subjects"
  return null
}

export function hubState(input: HubInput): HubState {
  if (failureKind(input)) return "error"
  if (isPending(input)) return "loading"
  const papers = paperCount(input.subjects)
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
  // Caught up only means something once we know there are decks to be caught up on.
  if (due === 0 && decks !== null) return "All caught up"
  return "Review your cards"
}

/** Where a student with no subject goes to add one: the onboarding wizard is the only subject editor. */
export const ADD_SUBJECT_PATH = "/student/onboard"

export function hubTiles(input: {
  firstTime: boolean
  primarySubject: string | null
  /** The subject list loaded and is empty. A failed load is not this: the error state explains that one. */
  noSubjects: boolean
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
    // With no subject the tile says why and leads to the one place that fixes it; a silent dead tile does neither.
    input.noSubjects
      ? { key: "set", title: "Practice set", status: "Add a subject first", tone: "tide", to: ADD_SUBJECT_PATH, disabled: false, opensSheet: false, count: null }
      : {
          key: "set",
          title: "Practice set",
          status: input.firstTime ? "Pick any topic" : "Build your own",
          tone: "tide",
          to: primary ? `/student/practice/${primary}` : null,
          disabled: primary === null,
          opensSheet: true,
          count: null,
        },
    {
      key: "cards",
      title: "Flashcards",
      status: cardsStatus(input.dueTotal, input.deckCount),
      tone: "violet",
      to: "/student/flashcards",
      disabled: false,
      opensSheet: false,
      count: input.dueTotal !== null && input.dueTotal > 0 ? input.dueTotal : null,
    },
    { key: "paper", title: "Past papers", status: "Print or do timed", tone: "mint", to: "/student/practice/papers", disabled: false, opensSheet: false, count: null },
    {
      key: "test",
      title: "Placement test",
      status: input.noSubjects
        ? "Needs a subject"
        : available
          ? available.minutes
            ? // No-break spaces keep "10 min" whole and the dot off the start of a wrapped line.
              `Find your level\u00a0· ${available.minutes}\u00a0min`
            : "Find your level"
          : noneAvailable
            ? "Not ready yet"
            : "Find your level",
      tone: "sea",
      to: testTo,
      disabled: testTo === null,
      opensSheet: false,
      count: null,
    },
  ]
}

/** Binny speaks in two to four words (master rule), so the line is counted, not hoped for. */
export const BINNY_MAX_WORDS = 4

export function wordCount(text: string): number {
  return text.trim().split(/\s+/).length
}

/** The fullest line that fits: topic and marks, then the topic alone, then a line any topic fits. */
function winLine(top: WinBackRow): string {
  const candidates = [`${top.label} first. +${plural(top.marks, "mark")}.`, `${top.label} first.`]
  return candidates.find((c) => wordCount(c) <= BINNY_MAX_WORDS) ?? "Win marks back."
}

function binnyFor(state: HubState, top: WinBackRow | undefined, papers: number): HubView["binny"] {
  if (state === "firstTime") return { mood: "open", line: "Start with a scan." }
  if (state === "sparse") return { mood: "happy", line: "Good start. Keep going." }
  if (state === "normal") {
    if (top) return { mood: "happy", line: winLine(top) }
    // Sets done but nothing scanned: there was nothing to catch up on, so ask for a paper.
    if (papers === 0) return { mood: "happy", line: "Scan a paper next." }
    return { mood: "happy", line: "All caught up." }
  }
  return null
}

function paperCount(subjects: readonly HubSubject[]): number {
  return subjects.reduce((sum, s) => sum + s.papers, 0)
}

export function practiceHubView(input: HubInput): HubView {
  const state = hubState(input)
  const allWinBack = winBackRows(input.subjects, input.topics)
  const primarySubject = allWinBack[0]?.subjectCode ?? input.subjects[0]?.code ?? null
  const recentAll = recentRows(input.runs, input.subjects, input.now)
  const showsContent = state === "normal" || state === "sparse"
  const errorKind = state === "error" ? failureKind(input) : null
  // Runs load on their own source; with no subject to name them they still list, by code.
  const showsRecent = showsContent || errorKind === "subjects"
  const papers = paperCount(input.subjects)
  return {
    state,
    errorKind,
    notice: input.profileStatus === "error" && state !== "error" && state !== "loading" ? "subjects" : null,
    subtitle: showsContent && allWinBack.length > 0 ? `${plural(allWinBack.length, "topic")} to win back` : null,
    binny: binnyFor(state, allWinBack[0], papers),
    homework: state === "loading" ? null : pickHomework(input.homework, input.now),
    tiles: hubTiles({
      firstTime: state === "firstTime",
      primarySubject,
      noSubjects: state === "firstTime" && input.subjects.length === 0,
      dueTotal: input.dueTotal,
      deckCount: input.deckCount,
      placement: input.placement,
    }),
    winBack: showsContent ? allWinBack.slice(0, WIN_BACK_SHOWN) : [],
    winBackMore: showsContent ? allWinBack.slice(WIN_BACK_SHOWN) : [],
    recent: showsRecent ? recentAll.slice(0, RECENT_SHOWN) : [],
    recentMore: showsRecent ? recentAll.slice(RECENT_SHOWN) : [],
    showScanTip: state === "sparse" || (state === "normal" && papers === 0),
    primarySubject,
  }
}

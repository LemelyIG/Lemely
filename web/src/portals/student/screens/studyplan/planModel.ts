/*
 * L9 · the study plan's every decision, as one pure function of the week
 * overview. The screen renders what this returns and decides nothing.
 *
 * "Today" is `overview.today`, the server's day, never the browser clock.
 * Dates are compared as ISO strings, which sort in calendar order (K14).
 */

import type { StudyPlanOverviewDTO, StudyPlanSessionDTO, SubjectWeekDTO } from "@/lib/studyPlanTypes"
import {
  activityLabel,
  addDays,
  basedOnLine,
  examLine,
  formatMinutes,
  reasonLine,
  refusalCopy,
  spokenMinutes,
  startAction,
  weekdayLong,
  weekdayShort,
  whyBody,
  whyTopicsHint,
  COPY,
  type NextExam,
  type RefusalCopy,
  type StartAction,
} from "./planCopy"

export type SessionStatus = "done" | "missed" | "today" | "later" | "anyDay"
export interface MoveDay { date: string; label: string }
export interface SessionVM {
  id: string
  subjectCode: string
  subjectName: string
  dotIndex: number
  activity: string
  activityLabel: string
  title: string
  minutes: number
  minutesLabel: string
  date: string
  dayShort: string
  anyDay: boolean
  status: SessionStatus
  why: string | null
  whyBody: string
  start: StartAction | null
  canMove: boolean
  moveDays: MoveDay[]
}
export interface DayCell { date: string; letter: string; label: string; count: number; isToday: boolean; allDone: boolean; hasMissed: boolean }
export interface FilterChip { code: string | null; label: string; dotIndex: number | null; selected: boolean }
export interface HeaderModel { title: string; sub: string; examDate: string | null; filters: FilterChip[] }
export interface PendingSubject { subjectCode: string; subjectName: string; kind: "notGenerated" | "refused" }
export interface DayGroup { date: string; label: string; sessions: SessionVM[] }
export interface PlanBody {
  ring: [number, number, number]
  ringLabel: string
  today: { date: string; heading: string; sub: string; sessions: SessionVM[] }
  missed: SessionVM[]
  week: { show: boolean; days: DayCell[]; anyDay: SessionVM[] }
  later: DayGroup[]
  done: { count: number; title: string; daysLabel: string; openByDefault: boolean; sessions: SessionVM[] }
  basedOn: string
  subjectTop: { targetGrade: string | null; exam: string | null } | null
  whyTopics: { topic: string; pct: number; tone: "w" | "m" }[]
  whyHint: string | null
  pending: PendingSubject[]
  firstOpenId: string | null
  binnyLine: string
}
export interface WeekDoneStat { value: string; label: string; tone: "ok" | "primary" }
export type PlanScreen =
  | { kind: "noSubjects" }
  | { kind: "firstRun"; header: HeaderModel; codesToBuild: string[] }
  | { kind: "needPaper"; header: HeaderModel; placementCode: string; copy: RefusalCopy }
  | { kind: "nothingScheduled"; header: HeaderModel; practiceCode: string; basedOn: string; scopeCodes: string[]; pending: PendingSubject[] }
  | { kind: "weekDone"; header: HeaderModel; body: string; stats: WeekDoneStat[]; practiceCode: string; scopeCodes: string[]; all: SessionVM[] }
  | { kind: "plan"; header: HeaderModel; body: PlanBody; scopeCodes: string[]; all: SessionVM[] }

export interface PlanModelInput {
  overview: StudyPlanOverviewDTO
  filter: string | null
  subjectName: (code: string) => string
  targetGrade: (code: string) => string | null
  nextExam: (code: string) => NextExam | null
  /** Noon of `overview.today`, for day counts. */
  now: Date
  xp: { weekXp: number; streak: number } | null
}

/** Below this accuracy a why-topic chip uses the "work on" tone (`.tm.w`). */
const WEAK_PCT = 60

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)
const minutesOf = (list: { minutes: number }[]) => list.reduce((t, s) => t + s.minutes, 0)

export function resolveFilter(overview: StudyPlanOverviewDTO, code: string | undefined): string | null {
  if (!code) return null
  return overview.subjects.some((s) => s.subjectCode === code) ? code : null
}

function statusOf(s: StudyPlanSessionDTO, today: string): SessionStatus {
  if (s.completedAt !== null) return "done"
  if (s.anyDay) return "anyDay"
  if (s.date < today) return "missed"
  if (s.date === today) return "today"
  return "later"
}

function moveDaysFor(date: string, today: string, weekEnd: string): MoveDay[] {
  const days: MoveDay[] = []
  for (let d = today; d <= weekEnd; d = addDays(d, 1)) {
    if (d !== date) days.push({ date: d, label: d === today ? "Today" : weekdayShort(d) })
  }
  return days
}

function buildSession(
  s: StudyPlanSessionDTO,
  subject: SubjectWeekDTO,
  dotIndex: number,
  input: PlanModelInput,
): SessionVM {
  const { overview } = input
  const status = statusOf(s, overview.today)
  const moveDays = moveDaysFor(s.date, overview.today, overview.weekEnd)
  const movable = status === "today" || status === "later" || status === "missed"
  return {
    id: s.id,
    subjectCode: subject.subjectCode,
    subjectName: input.subjectName(subject.subjectCode),
    dotIndex,
    activity: s.activityType,
    activityLabel: activityLabel(s.activityType),
    title: s.topic,
    minutes: s.durationMinutes,
    minutesLabel: formatMinutes(s.durationMinutes),
    date: s.date,
    dayShort: weekdayShort(s.date),
    anyDay: s.anyDay,
    status,
    why: reasonLine(s.reason),
    whyBody: whyBody({ reason: s.reason, topic: s.topic, targetGrade: input.targetGrade(subject.subjectCode) }),
    start: startAction(s.activityType, subject.subjectCode, s.reason),
    canMove: movable && moveDays.length > 0,
    moveDays: movable ? moveDays : [],
  }
}

/** Today's goals by kind: practice or review, flashcards, a paper. A paper for any other day is the week's, never today's. */
function todayGoalGroups(sessions: SessionVM[], today: string): SessionVM[][] {
  const todays = sessions.filter((v) => v.date === today && !v.anyDay)
  return [
    todays.filter((v) => v.activity === "practice" || v.activity === "review"),
    todays.filter((v) => v.activity === "flashcards"),
    todays.filter((v) => v.activity === "past_paper"),
  ]
}

/** The ring's three segments: today's practice and flashcards, then the week's papers. */
function ringGroups(sessions: SessionVM[], today: string): [SessionVM[], SessionVM[], SessionVM[]] {
  const [practice, flashcards] = todayGoalGroups(sessions, today)
  return [practice, flashcards, sessions.filter((v) => v.activity === "past_paper")]
}

export function ringParts(sessions: SessionVM[], today: string): [number, number, number] {
  const part = (list: SessionVM[]) =>
    list.length === 0 ? 0 : list.filter((v) => v.status === "done").length / list.length
  const [a, b, c] = ringGroups(sessions, today)
  return [part(a), part(b), part(c)]
}

function earliest(dates: (string | null)[]): string | null {
  const real = dates.filter((d): d is string => d !== null).sort()
  return real[0] ?? null
}

function buildHeader(input: PlanModelInput, scope: SubjectWeekDTO[], sessions: SessionVM[] | null): HeaderModel {
  const { overview, filter } = input
  const filters: FilterChip[] =
    overview.subjects.length < 2
      ? []
      : [
          { code: null, label: "All", dotIndex: null, selected: filter === null },
          ...overview.subjects.map((s, i) => ({
            code: s.subjectCode,
            label: input.subjectName(s.subjectCode),
            dotIndex: i,
            selected: filter === s.subjectCode,
          })),
        ]
  let sub: string = COPY.noPlanSub
  if (sessions) {
    const planned = formatMinutes(minutesOf(sessions))
    sub = filter
      ? `${input.subjectName(filter)} · ${sessions.length} ${plural(sessions.length, "session", "sessions")} · ${planned}`
      : `${sessions.filter((v) => v.status === "done").length} of ${sessions.length} done · ${planned}`
  }
  return {
    title: COPY.title,
    sub,
    examDate: earliest(scope.map((s) => input.nextExam(s.subjectCode)?.date ?? null)),
    filters,
  }
}

function sortVMs(list: SessionVM[]): SessionVM[] {
  return [...list].sort((a, b) => a.date.localeCompare(b.date) || a.dotIndex - b.dotIndex)
}

export function planScreen(raw: PlanModelInput): PlanScreen {
  const { overview } = raw
  if (overview.subjects.length === 0) return { kind: "noSubjects" }
  // A stale `?subject=` code falls back to all subjects, so the scope is never empty.
  const filter = resolveFilter(overview, raw.filter ?? undefined)
  const input: PlanModelInput = { ...raw, filter }

  const scope = filter ? overview.subjects.filter((s) => s.subjectCode === filter) : overview.subjects
  const scopeCodes = scope.map((s) => s.subjectCode)
  const available = scope.filter((s) => s.generated && s.plan?.available)
  // `generated` with no plan body is as good as not built yet.
  const notGenerated = scope.filter((s) => !s.generated || !s.plan)
  const refused = scope.filter((s) => s.generated && s.plan && !s.plan.available)
  const dotIndex = (code: string) => overview.subjects.findIndex((s) => s.subjectCode === code)

  if (available.length === 0) {
    const header = buildHeader(input, scope, null)
    if (notGenerated.length > 0) {
      return { kind: "firstRun", header, codesToBuild: notGenerated.map((s) => s.subjectCode) }
    }
    const first = refused[0]
    return { kind: "needPaper", header, placementCode: first.subjectCode, copy: refusalCopy(first.plan?.reason ?? null) }
  }

  const pending: PendingSubject[] = [
    ...notGenerated.map((s) => ({ subjectCode: s.subjectCode, subjectName: input.subjectName(s.subjectCode), kind: "notGenerated" as const })),
    ...refused.map((s) => ({ subjectCode: s.subjectCode, subjectName: input.subjectName(s.subjectCode), kind: "refused" as const })),
  ]
  const all = sortVMs(
    available.flatMap((subject) =>
      (subject.plan?.sessions ?? []).map((s) => buildSession(s, subject, dotIndex(subject.subjectCode), input)),
    ),
  )
  const header = buildHeader(input, scope, all)
  const paperCount = scope.reduce((n, s) => n + s.paperCount, 0)

  if (all.length === 0) {
    return { kind: "nothingScheduled", header, practiceCode: available[0].subjectCode, basedOn: basedOnLine(paperCount), scopeCodes, pending }
  }

  if (all.every((v) => v.status === "done")) {
    const stats: WeekDoneStat[] = [{ value: String(all.length), label: plural(all.length, "session", "sessions"), tone: "ok" }]
    if (input.xp) {
      stats.push({ value: `+${input.xp.weekXp}`, label: "XP", tone: "primary" })
      stats.push({ value: String(input.xp.streak), label: plural(input.xp.streak, "day in a row", "days in a row"), tone: "ok" })
    }
    return {
      kind: "weekDone",
      header,
      body: `All ${all.length} ${plural(all.length, "session", "sessions")}, ${formatMinutes(minutesOf(all))}.`,
      stats,
      practiceCode: available[0].subjectCode,
      scopeCodes,
      all,
    }
  }

  return { kind: "plan", header, body: buildBody(input, scope, all, pending, paperCount), scopeCodes, all }
}

function buildBody(
  input: PlanModelInput,
  scope: SubjectWeekDTO[],
  all: SessionVM[],
  pending: PendingSubject[],
  paperCount: number,
): PlanBody {
  const { overview, filter } = input
  const today = overview.today
  const openToday = all.filter((v) => v.status === "today")
  const anyToday = all.filter((v) => v.date === today && !v.anyDay)
  const missed = all.filter((v) => v.status === "missed")
  const anyDay = all.filter((v) => v.status === "anyDay")
  const later = all.filter((v) => v.status === "later")
  const done = all.filter((v) => v.status === "done")
  const ring = ringParts(all, today)
  // Today's count covers today's goals only. A goal with nothing planned today is not one the student can miss.
  const goals = todayGoalGroups(all, today).filter((g) => g.length > 0)
  const goalsPlanned = goals.length
  const goalsDone = goals.filter((g) => g.every((v) => v.status === "done")).length
  // The week's papers get their own line, so a paper on another day never reads as a goal for today.
  const weekPapers = all.filter((v) => v.activity === "past_paper")
  const papersDone = weekPapers.filter((v) => v.status === "done").length

  const days: DayCell[] = []
  for (let d = overview.weekStart; d <= overview.weekEnd; d = addDays(d, 1)) {
    const on = all.filter((v) => v.date === d)
    days.push({
      date: d,
      letter: weekdayShort(d).charAt(0),
      label: weekdayLong(d),
      count: on.length,
      isToday: d === today,
      allDone: on.length > 0 && on.every((v) => v.status === "done"),
      hasMissed: on.some((v) => v.status === "missed"),
    })
  }

  const laterGroups: DayGroup[] = []
  for (const v of later) {
    const last = laterGroups[laterGroups.length - 1]
    if (last && last.date === v.date) last.sessions.push(v)
    else laterGroups.push({ date: v.date, label: v.date > overview.weekEnd ? `Next ${v.dayShort}` : v.dayShort, sessions: [v] })
  }

  const doneDays = [...new Set(done.map((v) => v.date))].sort().map(weekdayShort)
  const focus = filter ? scope[0] : null
  const exam = focus ? input.nextExam(focus.subjectCode) : null
  const target = focus ? input.targetGrade(focus.subjectCode) : null

  return {
    ring,
    ringLabel: [
      goalsPlanned === 0
        ? "Today: nothing planned"
        : `Today: ${goalsDone} of ${goalsPlanned} ${plural(goalsPlanned, "goal", "goals")} done`,
      weekPapers.length > 0
        ? `This week: ${papersDone} of ${weekPapers.length} ${plural(weekPapers.length, "paper", "papers")} done`
        : null,
    ]
      .filter((part): part is string => part !== null)
      .join(". "),
    today: {
      date: today,
      heading: `Today · ${weekdayLong(today)}`,
      sub:
        openToday.length > 0
          ? `${openToday.length} ${plural(openToday.length, "session", "sessions")} · ${formatMinutes(minutesOf(openToday))}`
          : anyToday.length > 0
            ? "Done for today"
            : "Nothing planned today",
      sessions: openToday,
    },
    missed,
    week: { show: filter === null || anyDay.length > 0, days, anyDay },
    later: laterGroups,
    done: {
      count: done.length,
      title: filter ? `${done.length} done` : `${done.length} done this week`,
      daysLabel: doneDays.join(" · "),
      openByDefault: filter !== null,
      sessions: done,
    },
    basedOn: basedOnLine(paperCount),
    subjectTop: focus && (target || exam) ? { targetGrade: target, exam: exam ? examLine(exam, input.now) : null } : null,
    whyTopics: focus
      ? focus.weakTopics.map((t) => ({ topic: t.topic, pct: t.accuracyPct, tone: t.accuracyPct < WEAK_PCT ? ("w" as const) : ("m" as const) }))
      : [],
    whyHint: focus && focus.weakTopics.length > 0 ? whyTopicsHint(input.subjectName(focus.subjectCode), focus.paperCount) : null,
    pending,
    firstOpenId: (openToday[0] ?? missed[0] ?? anyDay[0] ?? later[0] ?? null)?.id ?? null,
    binnyLine:
      openToday.length > 0
        ? `${spokenMinutes(minutesOf(openToday))} today.`
        : anyToday.length > 0
          ? "Done for today."
          : missed.length > 0
            ? `${missed.length} to catch up.`
            : "Nothing due today.",
  }
}

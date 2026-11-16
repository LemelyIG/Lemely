/*
 * Student Home view model (lane L1). Pure: no React, no fetching, no clock
 * reads. The server's `localDate`/`localHour` are the student's own civil
 * time, so the same payload always renders the same screen. Every decision
 * the Home screen makes lives here: the stage moment, Binny's mood, motion
 * and line, the button and its door, which rows show, and every label.
 *
 * Copy rules (web/scripts/check_copy.mjs): no "!" ending a sentence, no em
 * dash as punctuation. Binny's line is the stage headline from the approved
 * mock (see plan "Needs user decision" item 2).
 */
import type { BinnyMood, BinnyMotion } from "@/components/redesign"
import type {
  HomeMoment,
  HomeMomentKind,
  PaperMoment,
  StudentHome,
} from "@/lib/studentHomeTypes"
import { flashcardsTarget, homeRoutes, planTarget, practiceTarget } from "./routes"

export const EXAM_NEAR_DAYS = 30
export const SCAN_NUDGE_DAYS = 7
const DAY_MS = 86_400_000
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

export const STAGE_PRIORITY: readonly HomeMomentKind[] = [
  "marking",
  "result",
  "tough",
  "teacherReply",
  "streakAtRisk",
  "goalDone",
  "backAfterBreak",
]

export type StageKind = HomeMomentKind | "session" | "morning" | "scanNext" | "firstRun"

export interface StageVm {
  /** Stable id for "Not now", e.g. `result:5`. */
  key: string
  kind: StageKind
  mood: BinnyMood
  motion: BinnyMotion
  /** "Morning, Mariam." Shown before the line on phone and tablet only. */
  greeting: string | null
  line: string
  action: { label: string; to: string }
  dismissible: boolean
}

export type RowLeading =
  | { type: "grade"; grade: string }
  | { type: "initials"; text: string }
  | { type: "icon"; icon: "sheet" | "camera" | "class" | "trend" }

export interface RowVm {
  key: string
  kind: "result" | "teacher" | "homework" | "joinClass" | "sparse" | "scan"
  leading: RowLeading
  title: string
  sub: string
  to: string
}

/* ── helpers ──────────────────────────────────────────────────────────── */

export function parseDay(day: string): Date {
  return new Date(`${day}T00:00:00`)
}

function isoDay(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${d.getFullYear()}-${m}-${day}`
}

export function daysBetween(from: string, to: string): number {
  return Math.round((parseDay(to).getTime() - parseDay(from).getTime()) / DAY_MS)
}

export function firstName(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return "there"
  const base = trimmed.includes("@") ? trimmed.split("@")[0] : trimmed.split(/\s+/)[0]
  return base || "there"
}

export function shortGreeting(hour: number): string {
  if (hour >= 5 && hour < 12) return "Morning"
  if (hour >= 12 && hour < 18) return "Afternoon"
  return "Evening"
}

export function questionLabel(id: string): string {
  return /^q/i.test(id) ? id : `Q${id}`
}

export function shortSubject(name: string): string {
  return name.replace(/^Additional Mathematics$/, "Add Maths").replace(/^Additional /, "Add ")
}

export function initials(name: string): string {
  return name
    .replace(/[^\p{L}\s]/gu, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("")
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`
}

export function relativeDay(iso: string, localDate: string): string {
  const days = daysBetween(isoDay(new Date(iso)), localDate)
  if (days <= 0) return "today"
  if (days === 1) return "yesterday"
  if (days < 7) return `${days} days ago`
  if (days < 14) return "last week"
  return `${Math.floor(days / 7)} weeks ago`
}

function dueLabel(dueAt: string | null, localDate: string, overdue: boolean): string {
  if (overdue) return "Overdue"
  if (!dueAt) return "No due date"
  const due = new Date(dueAt)
  const days = daysBetween(localDate, isoDay(due))
  if (days <= 0) return "Due today"
  if (days === 1) return "Due tomorrow"
  if (days < 7) return `Due ${WEEKDAYS[due.getDay()]}`
  return `Due ${due.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`
}

export function isFirstRun(home: StudentHome): boolean {
  return home.floor.length === 0 && home.recentPapers.length === 0
}

export function examInfo(home: StudentHome): { date: string; days: number; near: boolean } | null {
  if (!home.nextExamOn) return null
  const days = daysBetween(home.localDate, home.nextExamOn)
  return { date: home.nextExamOn, days, near: days >= 0 && days <= EXAM_NEAR_DAYS }
}

/* ── stage ────────────────────────────────────────────────────────────── */

function motionFor(mood: BinnyMood): BinnyMotion {
  return mood === "happy" ? "hop" : "idle"
}

function stage(
  key: string,
  kind: StageKind,
  mood: BinnyMood,
  line: string,
  action: { label: string; to: string },
  dismissible = true,
  greeting: string | null = null,
): StageVm {
  return { key, kind, mood, motion: motionFor(mood), greeting, line, action, dismissible }
}

/** "an A", "an A*", "an E", "an F", "a B", "a U". */
export function withArticle(grade: string): string {
  return `${/^[AEF]/.test(grade) ? "an" : "a"} ${grade}`
}

function paperStage(m: PaperMoment): StageVm {
  const focus = m.focusQuestion ? questionLabel(m.focusQuestion) : null
  const to = homeRoutes.result(m.paperId, "lost")
  if (m.kind === "tough") {
    return stage(
      `tough:${m.paperId}`,
      "tough",
      "sad",
      `${m.subjectName} Paper ${m.paperNumber} was a tough one. Let's win back the easy marks first.`,
      { label: focus ? `Start with ${focus}` : "See my result", to },
    )
  }
  const up =
    m.previousGrade && m.previousGrade !== m.grade ? `, up from ${withArticle(m.previousGrade)}` : ""
  const fix = focus ? ` ${focus} is the one to fix.` : ""
  return stage(
    `result:${m.paperId}`,
    "result",
    "happy",
    `${m.awarded} out of ${m.maximum}. That's ${withArticle(m.grade)}${up}.${fix}`,
    { label: focus ? `Fix ${focus}` : "See my result", to },
  )
}

function momentStage(m: HomeMoment, home: StudentHome): StageVm {
  switch (m.kind) {
    case "marking": {
      const progress =
        m.questionsTotal != null && m.questionsDone != null
          ? `Marking your paper. ${m.questionsDone} of ${plural(m.questionsTotal, "question")} done.`
          : "Marking your paper now."
      const line = m.stale ? "Still marking. This one's taking a while." : progress
      return stage(`marking:${m.paperId}`, "marking", "thinking", line, {
        label: "Watch it mark",
        to: homeRoutes.scan,
      }, false)
    }
    case "result":
    case "tough":
      return paperStage(m)
    case "teacherReply": {
      const r = m.reply
      const added = r.marksAdded > 0 ? ` +${plural(r.marksAdded, "mark")}.` : ""
      return stage(
        `teacherReply:${r.reviewId}`,
        "teacherReply",
        "wink",
        `${r.teacherName} checked your ${questionLabel(r.questionId)}.${added}`,
        { label: "See the answer", to: r.paperId ? homeRoutes.result(r.paperId) : homeRoutes.notifications },
      )
    }
    case "streakAtRisk":
      return stage(
        `streakAtRisk:${home.localDate}`,
        "streakAtRisk",
        "thinking",
        `Your ${m.streakDays}-day streak ends at midnight. One quick set keeps it going.`,
        { label: "Keep my streak", to: practiceTarget(home) },
      )
    case "goalDone":
      return stage(
        `goalDone:${home.localDate}`,
        "goalDone",
        "happy",
        "Three for three today. That's you done. See you tomorrow.",
        { label: "See tomorrow's plan", to: planTarget(home) },
      )
    case "backAfterBreak":
      return stage(
        `backAfterBreak:${home.localDate}`,
        "backAfterBreak",
        "wink",
        `There you are. ${plural(m.daysAway, "day")} off is fine. Ease back in with five minutes.`,
        { label: "5-minute warm-up", to: practiceTarget(home) },
      )
  }
}

function fallbackStages(home: StudentHome): StageVm[] {
  const exam = examInfo(home)
  const near = exam?.near ? `${plural(exam.days, "day")} to exams. ` : null
  const name = firstName(home.studentName)
  const out: StageVm[] = []

  if (isFirstRun(home)) {
    out.push(
      stage("firstRun", "firstRun", "open", near ? `${near}Let's mark a paper.` : `Hi ${name}. Let's mark your first paper.`, {
        label: "Scan a paper",
        to: homeRoutes.scan,
      }, false),
    )
    return out
  }

  const session = home.todaySessions.find((s) => !s.done)
  if (session) {
    out.push(
      stage(
        `session:${session.sessionId}`,
        "session",
        "open",
        near ? `${near}Today: ${session.topic}.` : `Today's plan: ${session.topic}, ${session.minutes} minutes.`,
        { label: "Start", to: homeRoutes.session(session.subjectCode, session.sessionId) },
      ),
    )
  }

  const top = home.winBack[0]
  if (top) {
    const greeting = !near && home.localHour < 12 ? `${shortGreeting(home.localHour)}, ${name}.` : null
    out.push(
      stage(
        `morning:${top.subjectCode}:${top.topic}`,
        "morning",
        "open",
        near
          ? `${near}${top.topic} first, +${top.marks} marks.`
          : `${top.topic} cost you ${top.marks} marks last time. Ten minutes fixes most of it.`,
        { label: "Start 10 minutes", to: homeRoutes.practiceTopic(top.subjectCode, top.topic) },
        true,
        greeting,
      ),
    )
  }

  out.push(
    stage("scanNext", "scanNext", "open", near ? `${near}Scan your next paper.` : "Nothing to win back yet. Scan your next paper.", {
      label: "Scan a paper",
      to: homeRoutes.scan,
    }, false),
  )
  return out
}

export function stageCandidates(home: StudentHome): StageVm[] {
  const moments = [...home.moments].sort(
    (a, b) => STAGE_PRIORITY.indexOf(a.kind) - STAGE_PRIORITY.indexOf(b.kind),
  )
  return [...moments.map((m) => momentStage(m, home)), ...fallbackStages(home)]
}

export function pickStage(home: StudentHome, dismissed: ReadonlySet<string>): StageVm {
  const candidates = stageCandidates(home)
  return candidates.find((s) => !s.dismissible || !dismissed.has(s.key)) ?? candidates[candidates.length - 1]!
}

/* ── rows ─────────────────────────────────────────────────────────────── */

function teacherRow(home: StudentHome): RowVm | null {
  const r = home.teacherReplies[0]
  if (!r) return null
  const added = r.marksAdded > 0 ? ` · +${plural(r.marksAdded, "mark")}` : ""
  return {
    key: `teacher:${r.reviewId}`,
    kind: "teacher",
    leading: { type: "initials", text: initials(r.teacherName) },
    title: `${r.teacherName} checked your answer`,
    sub: `${questionLabel(r.questionId)}${added}`,
    to: r.paperId ? homeRoutes.result(r.paperId) : homeRoutes.notifications,
  }
}

function homeworkRow(home: StudentHome): RowVm | null {
  const h = home.homework[0]
  if (!h) return null
  return {
    key: `homework:${h.assignmentId}`,
    kind: "homework",
    leading: { type: "icon", icon: "sheet" },
    title: `${h.title} from ${h.teacherName}`,
    sub: `${dueLabel(h.dueAt, home.localDate, h.isOverdue)} · ${plural(h.questionCount, "question")}`,
    to: homeRoutes.practiceSet(h.assignmentId),
  }
}

export function alsoRows(home: StudentHome, current: StageVm, layout: "phone" | "desktop"): RowVm[] {
  const rows: (RowVm | null)[] = []
  const paper = home.moments.find(
    (m): m is PaperMoment => (m.kind === "result" || m.kind === "tough") && current.kind === m.kind,
  )
  if (paper) {
    rows.push({
      key: `result:${paper.paperId}`,
      kind: "result",
      leading: { type: "grade", grade: paper.grade },
      title: "See your full result",
      sub: `${paper.subjectName} · Paper ${paper.paperNumber}`,
      to: homeRoutes.result(paper.paperId),
    })
  }
  if (layout === "phone") {
    if (current.kind !== "teacherReply") rows.push(teacherRow(home))
    rows.push(homeworkRow(home))
  }
  if (home.classCount === 0) {
    rows.push({
      key: "joinClass",
      kind: "joinClass",
      leading: { type: "icon", icon: "class" },
      title: "Join your teacher's class",
      sub: "Enter the code they gave you",
      to: homeRoutes.classes,
    })
  }
  if (home.stats.papersMarked === 1) {
    rows.push({
      key: "sparse",
      kind: "sparse",
      leading: { type: "icon", icon: "trend" },
      title: "One more paper draws your trend",
      sub: "Scan your next paper",
      to: homeRoutes.scan,
    })
  }
  if (home.lastPaperAt && current.kind !== "scanNext" && current.kind !== "firstRun") {
    const days = daysBetween(isoDay(new Date(home.lastPaperAt)), home.localDate)
    if (days > SCAN_NUDGE_DAYS) {
      rows.push({
        key: "scan",
        kind: "scan",
        leading: { type: "icon", icon: "camera" },
        title: "Scan your next paper",
        sub: `Your last one was ${plural(days, "day")} ago`,
        to: homeRoutes.scan,
      })
    }
  }
  return rows.filter((r): r is RowVm => r !== null).slice(0, 2)
}

/* ── blocks ───────────────────────────────────────────────────────────── */

export function todayVm(home: StudentHome) {
  const g = home.goals
  const parts: [number, number, number] = [g.practice ? 1 : 0, g.flashcards ? 1 : 0, g.paperThisWeek ? 1 : 0]
  const doneCount = parts.reduce<number>((a, b) => a + b, 0)
  return {
    parts,
    doneCount,
    label: `${doneCount} of 3 today`,
    planTo: planTarget(home),
    chips: [
      { label: "Practice", done: g.practice, to: practiceTarget(home) },
      { label: "Flashcards", done: g.flashcards, to: flashcardsTarget(home) },
      { label: "Paper this week", done: g.paperThisWeek, to: homeRoutes.scan },
    ],
  }
}

export function weekVm(home: StudentHome) {
  const to = planTarget(home)
  return home.week.map((d) => {
    const name = WEEKDAYS[parseDay(d.day).getDay()]!
    const label = d.label ? `: ${d.label}` : ""
    return {
      day: d.day,
      letter: name[0]!,
      done: d.done,
      isToday: d.isToday,
      ariaLabel: `${name}${label}${d.done ? ", done" : ""}`,
      to,
    }
  })
}

/** The line under a subject grade: marks to the next grade, never "Top grade" while one exists. */
export function gradeGapLabel(f: { nextGrade: string | null; pointsToNext: number | null }): string {
  if (!f.nextGrade) return "Top grade"
  return f.pointsToNext != null ? `${plural(f.pointsToNext, "mark")} to ${f.nextGrade}` : `On the way to ${f.nextGrade}`
}

export function floorVm(home: StudentHome) {
  return home.floor.map((f) => ({
    code: f.code,
    name: shortSubject(f.name),
    grade: f.grade,
    sub: gradeGapLabel(f),
    to: homeRoutes.subject(f.code),
  }))
}

export function lastPaperVm(home: StudentHome) {
  const p = home.recentPapers[0]
  if (!p) return null
  return {
    grade: p.grade,
    title: `Last paper · ${shortSubject(p.subjectName)} P${p.paperNumber}`,
    sub: `${p.awarded}/${p.maximum} · ${relativeDay(p.recordedAt, home.localDate)}`,
    to: homeRoutes.result(p.paperId),
  }
}

export function winVm(home: StudentHome, kind: StageKind) {
  const limit = kind === "backAfterBreak" ? 1 : 3
  return home.winBack.slice(0, limit).map((t) => ({
    topic: t.topic,
    sub: shortSubject(t.subjectName),
    marks: t.marks,
    to: homeRoutes.practiceTopic(t.subjectCode, t.topic),
  }))
}

export function streakPillVm(home: StudentHome) {
  const s = home.streak
  const g = home.goals
  const label = s.current > 0 ? plural(s.current, "day") : s.longest > 0 ? "New streak" : "Start a streak"
  return { label, lit: g.practice && g.flashcards && g.paperThisWeek, to: homeRoutes.me }
}

export function bandVm(home: StudentHome) {
  const todayIdx = home.week.findIndex((d) => d.isToday)
  const weekNext: { when: string; what: string }[] = []
  const today = home.week[todayIdx]
  if (today?.label) weekNext.push({ when: "Today", what: today.label })
  const next = home.week.slice(todayIdx + 1).find((d) => d.label)
  if (next?.label) weekNext.push({ when: WEEKDAYS[parseDay(next.day).getDay()]!, what: next.label })
  return {
    weekNext,
    recent: home.recentPapers.map((p) => ({
      grade: p.grade,
      title: `${shortSubject(p.subjectName)} · Paper ${p.paperNumber}`,
      sub: `${p.awarded}/${p.maximum} · ${relativeDay(p.recordedAt, home.localDate)}`,
      to: homeRoutes.result(p.paperId),
    })),
    classRows: [teacherRow(home), homeworkRow(home)].filter((r): r is RowVm => r !== null),
  }
}

export interface HomeVm {
  firstRun: boolean
  heading: string
  stage: StageVm
  also: { phone: RowVm[]; desktop: RowVm[] }
  today: ReturnType<typeof todayVm>
  week: ReturnType<typeof weekVm>
  floor: ReturnType<typeof floorVm>
  last: ReturnType<typeof lastPaperVm>
  win: ReturnType<typeof winVm>
  streakPill: ReturnType<typeof streakPillVm>
  exam: ReturnType<typeof examInfo>
  band: ReturnType<typeof bandVm>
  allPapersTo: string | null
}

export function homeView(home: StudentHome, dismissed: ReadonlySet<string>): HomeVm {
  const current = pickStage(home, dismissed)
  const last = home.recentPapers[0]
  return {
    firstRun: isFirstRun(home),
    heading: `${shortGreeting(home.localHour)}, ${firstName(home.studentName)}`,
    stage: current,
    also: { phone: alsoRows(home, current, "phone"), desktop: alsoRows(home, current, "desktop") },
    today: todayVm(home),
    week: weekVm(home),
    floor: floorVm(home),
    last: lastPaperVm(home),
    win: winVm(home, current.kind),
    streakPill: streakPillVm(home),
    exam: examInfo(home),
    band: bandVm(home),
    // "All papers" has no screen yet; it opens the last paper's subject (item 6).
    allPapersTo: last ? homeRoutes.subject(last.subjectCode) : null,
  }
}

/*
 * Wire types for `GET /api/student/home` (lane L1). Mirrors
 * `lemely/web/schemas_student_home.py` field for field. Dates are ISO strings:
 * `YYYY-MM-DD` for `date`, full ISO-8601 for `datetime`.
 */

export interface MarkingMoment {
  kind: "marking"
  paperId: string
  filename: string | null
  startedAt: string | null
  stale: boolean
  questionsDone: number | null
  questionsTotal: number | null
}

export interface PaperMoment {
  kind: "result" | "tough"
  paperId: string
  subjectCode: string
  subjectName: string
  paperNumber: number
  awarded: number
  maximum: number
  grade: string
  previousGrade: string | null
  focusQuestion: string | null
  recordedAt: string
}

export interface TeacherReply {
  reviewId: string
  teacherName: string
  questionId: string
  subjectCode: string | null
  subjectName: string | null
  paperNumber: number | null
  marksAdded: number
  /** History index for `/student/result/:paperId`; `null` when the paper is not in history. */
  paperId: string | null
  resolvedAt: string
}

export interface TeacherReplyMoment {
  kind: "teacherReply"
  reply: TeacherReply
}

export interface StreakMoment {
  kind: "streakAtRisk" | "goalDone"
  streakDays: number
}

export interface BackMoment {
  kind: "backAfterBreak"
  daysAway: number
}

export type HomeMoment = MarkingMoment | PaperMoment | TeacherReplyMoment | StreakMoment | BackMoment
export type HomeMomentKind = HomeMoment["kind"]

export interface HomeGoals {
  practice: boolean
  flashcards: boolean
  paperThisWeek: boolean
}

export interface PlanSession {
  sessionId: string
  subjectCode: string
  topic: string
  minutes: number
  done: boolean
}

export interface WeekDay {
  day: string
  label: string | null
  done: boolean
  isToday: boolean
}

export interface HomeStreak {
  current: number
  longest: number
  lastActiveOn: string | null
  freezesAvailable: number
}

export interface FloorSubject {
  code: string
  name: string
  grade: string
  previousGrade: string | null
  nextGrade: string | null
  pointsToNext: number | null
  papers: number
}

export interface WinBackTopic {
  topic: string
  subjectCode: string
  subjectName: string
  marks: number
}

export interface RecentPaper {
  paperId: string
  subjectCode: string
  subjectName: string
  paperNumber: number
  awarded: number
  maximum: number
  grade: string
  recordedAt: string
}

export interface Homework {
  assignmentId: string
  title: string
  subjectCode: string
  teacherName: string
  dueAt: string | null
  questionCount: number
  isOverdue: boolean
}

export interface HomeStats {
  papersMarked: number
  marksWonBack: number
  bestGrade: { grade: string; subjectCode: string } | null
}

export interface HomeActivity {
  kind: "paper" | "practice" | "teacher"
  title: string
  sub: string
  at: string
}

export interface StudentHome {
  studentName: string
  localDate: string
  localHour: number
  moments: HomeMoment[]
  goals: HomeGoals
  todaySessions: PlanSession[]
  week: WeekDay[]
  streak: HomeStreak
  nextExamOn: string | null
  floor: FloorSubject[]
  winBack: WinBackTopic[]
  recentPapers: RecentPaper[]
  lastPaperAt: string | null
  teacherReplies: TeacherReply[]
  homework: Homework[]
  classCount: number
  stats: HomeStats
  activity: HomeActivity[]
}

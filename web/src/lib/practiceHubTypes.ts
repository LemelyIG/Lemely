/*
 * Wire types for the Practice tab (L4): `lemely/web/schemas_practice_hub.py`,
 * plus the existing `GET /api/student/quizzes` list (`StudentQuizListItemDTO`,
 * `lemely/web/schemas_quiz.py`), which has had no frontend type until now.
 */

export type PracticeRunStatus = "not_started" | "in_progress" | "submitted" | "marked"

/** One practice set in "Recent". Marks are non-null only when `status === "marked"`. */
export interface PracticeRun {
  assignmentId: string
  subjectCode: string
  title: string
  /** Distinct topics, most frequent first. */
  topics: string[]
  status: PracticeRunStatus
  questionCount: number
  answeredCount: number
  awardedMarks: number | null
  maximumMarks: number | null
  timeLimitMinutes: number | null
  lastActivityAt: string
}

export interface PracticeRuns {
  runs: PracticeRun[]
}

/** One past paper the student can print, or has already done. */
export interface PastPaper {
  paperId: string
  code: string
  subjectCode: string
  paperNumber: number
  paperVariant: number
  sessionLabel: string
  durationMinutes: number | null
  totalMarks: number | null
  questionCount: number
  awardedMarks: number | null
  maximumMarks: number | null
}

export interface PastPapers {
  subjectCode: string
  papers: PastPaper[]
}

/** One row of `GET /api/student/quizzes`. `teacherName` is null for the student's own sets. */
export interface StudentQuizListItem {
  assignmentId: string
  quizTitle: string
  subjectCode: string
  className: string | null
  teacherName: string | null
  assignedAt: string
  dueAt: string | null
  closesAt: string | null
  questionCount: number
  timeLimitMinutes: number | null
  submissionStatus: string
  isOpen: boolean
  isOverdue: boolean
}

export interface StudentQuizList {
  quizzes: StudentQuizListItem[]
}

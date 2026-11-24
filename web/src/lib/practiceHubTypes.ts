/*
 * Wire types for the Practice tab (L4): `lemely/web/schemas_practice_hub.py`.
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

/*
 * TS interfaces mirroring `lemely/web/schemas_placement.py` (placement-test
 * routes) and the student-facing slice of `lemely/web/schemas_quiz.py` that
 * placement's take/save/submit reuses verbatim (D4.6 §4 — there are no
 * parallel placement take routes; S-04 is built on
 * `/api/student/quizzes/{assignmentId}/...`, the same routes P4.9/P5's
 * practice quizzes will use). Field names are camelCase to match the wire.
 */

// ── `/api/student/placement/*` (P4.4 chunk B-4, D4.6) ───────────────────

/**
 * `GET /api/student/placement/{subjectCode}/availability` response, and the
 * identical shape carried in a `POST /api/student/placement` 409's `detail`.
 * `reason` is a machine-readable `UnavailableReason` value
 * (`lemely.core.placement.UnavailableReason`) — `null` only when `available`
 * is `true`. S-03 renders a specific message per reason, never a generic
 * failure.
 */
export interface PlacementAvailability {
  available: boolean
  reason: string | null
  questionCount: number
  topicCount: number
  estimatedMinutes: number
}

export interface CreatePlacementRequest {
  subjectCode: string
}

/** 201 response for `POST /api/student/placement` — S-03 -> S-04. */
export interface CreatePlacementResponse {
  assignmentId: string
  quizId: string
  questionCount: number
  topicCount: number
  estimatedMinutes: number
}

export interface PlacementQuestionResult {
  questionRef: string
  /** `null` is an unknown topic, never a topic named "unknown". */
  topic: string | null
  awardedMarks: number
  maximumMarks: number
}

export interface PlacementTopicBreakdown {
  topic: string
  lostMarks: number
  maximumMarks: number
  accuracy: number
}

/**
 * `GET /api/student/placement/{assignmentId}/result` response — S-05's
 * payload. `marked=false` (with `awardedMarks`/`maximumMarks` both `null`)
 * means the submission has not been marked yet: S-05 must say so, never
 * render a half result with zeros standing in for "not yet known".
 * `spansMultipleBands=false` forbids showing any working-level estimate —
 * the sample was too narrow, and S-05 shows strongest/weakest topics only.
 */
export interface PlacementResult {
  assignmentId: string
  quizId: string
  subjectCode: string
  marked: boolean
  awardedMarks: number | null
  maximumMarks: number | null
  questions: PlacementQuestionResult[]
  topicBreakdown: PlacementTopicBreakdown[]
  spansMultipleBands: boolean
}

// ── `/api/student/quizzes/*` take/save/submit (P3.5 chunk E, reused by
// placement verbatim — D4.6 §4) ─────────────────────────────────────────

export interface StudentQuizHeader {
  quizTitle: string
  subjectCode: string
  /** `null` for a class-less assignment — every placement test (D4.6 §3). */
  className: string | null
  /** `null` for a student-owned quiz, which has no teacher — every placement test. */
  teacherName: string | null
  dueAt: string | null
  closesAt: string | null
  /** `null` on a placement quiz by design — S-04 shows elapsed time, not a
   * countdown, for placement (`lemely.core.placement` module docstring). */
  timeLimitMinutes: number | null
  submissionStatus: string
  isOpen: boolean
  isOverdue: boolean
  unansweredCount: number
}

/**
 * One question in the take payload. Never carries `modelAnswer`,
 * `markSchemePoints`, or `mcqAnswer` — there is no field for any of the
 * three anywhere on this DTO, by construction.
 */
export interface StudentQuizQuestion {
  id: string
  questionRef: string
  position: number
  /** `null` is an unknown topic, never a topic named "unknown". */
  topic: string | null
  difficulty: string
  questionType: string
  prompt: string
  totalMarks: number
  mcqOptions: string[] | null
  answerText: string | null
  workingText: string | null
  answeredAt: string | null
}

/** `GET /api/student/quizzes/{assignmentId}` response — the take payload. */
export interface StudentQuizTake {
  header: StudentQuizHeader
  questions: StudentQuizQuestion[]
}

/**
 * Body for `PUT /api/student/quizzes/{assignmentId}/answers/{questionRef}`.
 * An omitted field leaves the stored value untouched; `""` explicitly
 * clears it. Never send a field that did not change — build this with only
 * the touched key present (`buildAnswerSavePayload` in
 * `components/quiz/quizTakerData.ts` is the single enforcement point).
 */
export interface SaveAnswerRequest {
  answerText?: string | null
  workingText?: string | null
}

export interface SaveAnswerResponse {
  questionRef: string
  answerText: string | null
  workingText: string | null
  answeredAt: string | null
}

/** Response for `POST /api/student/quizzes/{assignmentId}/submit`. No
 * marking has happened yet — `submissionStatus` is always `"submitted"`. */
export interface SubmitQuizResponse {
  submissionStatus: string
  answeredCount: number
  unansweredCount: number
}

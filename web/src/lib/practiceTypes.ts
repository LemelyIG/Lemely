/*
 * TS interfaces mirroring `lemely/web/schemas_practice.py` (practice-generator
 * routes, P4.9). Field names are camelCase to match the wire, following
 * `placementTypes.ts`'s convention exactly. Take/save/submit for a created
 * practice set reuse the existing `StudentQuizTake`/`SaveAnswerRequest`/
 * `SubmitQuizResponse` shapes in `placementTypes.ts` verbatim (D4.6 §4's
 * payoff — the same `/api/student/quizzes/{assignmentId}/...` routes,
 * composed via `QuizTaker`) — nothing here duplicates them.
 */

// ── `/api/student/practice/*` (P4.5) ────────────────────────────────────

/** Shared filter set for a preview or a create (S-20). `topics` is ignored
 * server-side when `weakTopicsOnly` is `true` — the topic filter is derived
 * from the caller's own recorded weaknesses instead. Empty/`null`
 * `difficultyBands`/`source` means "no filter on that dimension". */
export interface PracticeFilterSet {
  subjectCode: string
  count: number
  topics: string[]
  weakTopicsOnly: boolean
  difficultyBands: string[]
  source: string | null
}

/**
 * `GET /api/student/practice/{subjectCode}/preview` response — S-20's live
 * match count. `available: true` covers the honest-shortfall case too
 * (`reason: "insufficient_pool"`, `availableCount < requestedCount`) — never
 * padded, never silently shortened. `available: false` is a real refusal
 * (`no_questions` / `no_weaknesses`), not a rendering choice.
 */
export interface PracticePreview {
  available: boolean
  reason: string | null
  requestedCount: number
  availableCount: number
  topics: string[]
}

/** 201 response for `POST /api/student/practice` — S-20 -> S-21. */
export interface CreatePracticeResponse {
  assignmentId: string
  quizId: string
  questionCount: number
  requestedCount: number
  topics: string[]
  reason: string | null
}

/** One question in the print/export payload — deliberately answer-free: no
 * `modelAnswer`/`markSchemePoints`/`mcqAnswer` field exists on this type at
 * all, matching the DTO's structural exclusion. */
export interface PracticeExportQuestion {
  questionRef: string
  position: number
  topic: string | null
  difficulty: string
  questionType: string
  prompt: string
  totalMarks: number
  mcqOptions: string[] | null
}

/** `GET /api/student/practice/{assignmentId}/export` response — the
 * print/export payload. */
export interface PracticeExport {
  assignmentId: string
  quizId: string
  subjectCode: string
  title: string
  questions: PracticeExportQuestion[]
}

/** One marked question's outcome. `confidenceBand`/`confidenceScore` are
 * non-nullable by construction — every displayed mark carries its
 * confidence. No model-answer field exists here either. */
export interface PracticeResultQuestion {
  questionRef: string
  position: number
  topic: string | null
  totalMarks: number
  awardedMarks: number
  confidenceBand: string
  confidenceScore: number
}

/**
 * `GET /api/student/practice/{assignmentId}/result` response — S-21's poll
 * target. `marked: false` (with `awardedMarks`/`maximumMarks` both `null`
 * and `questions` empty) means the submission has not been marked yet —
 * never a fabricated zero score. `submissionStatus` distinguishes "not
 * submitted yet" from "submitted, being marked".
 */
export interface PracticeResult {
  assignmentId: string
  quizId: string
  subjectCode: string
  marked: boolean
  submissionStatus: string
  awardedMarks: number | null
  maximumMarks: number | null
  questions: PracticeResultQuestion[]
}

/** One servable topic, its real unpadded count, and the syllabus group it
 * sits under. The bank mixes taxonomy levels — a broad group
 * ("1 Motion, forces and energy") and a narrower one ("1.2 Motion") can come
 * back as peers with disjoint rows, so `syllabusGroup` is what S-20 nests
 * on, never a flat list. */
export interface PracticeTopicCount {
  topic: string
  availableCount: number
  syllabusGroup: string
}

/**
 * `GET /api/student/practice/{subjectCode}/topics` response — S-20's
 * topic-selection payload. `weakTopics` is the caller's own weak-topic
 * vocabulary as the server understands it — S-20 prefills its chips from
 * this, never from a screen-local weakness list (there are two distinct
 * weak-topic vocabularies in this codebase and only this one joins against
 * the practice pool). `untopicedCount` is reported separately from `topics`
 * — an untopiced row is legitimate practice material, just not a topic, and
 * must never be rendered as one.
 */
export interface PracticeTopics {
  subjectCode: string
  topics: PracticeTopicCount[]
  weakTopics: string[]
  untopicedCount: number
}

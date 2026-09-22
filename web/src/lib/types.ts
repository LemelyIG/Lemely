/*
 * Shared domain types. These mirror the Lemely Python core (lemely/core/schemas
 * — AccuracyReport, marker sources, grades) so the stubbed API layer can later
 * be swapped for the real FastAPI endpoints without touching screen code.
 */

export type PortalId = "teacher" | "student"

/** How a question was marked — the mock's 🔢 / 🤖 / ❓ legend.
 *
 * "dropped" (US-038, migration `0038_marker_source_dropped`): the model
 * returned an answer for this question, but extraction discarded it as
 * malformed. Distinct from "missing" — nothing was ever attempted. */
export type MarkerSource = "deterministic" | "ai" | "missing" | "dropped"

/*
 * The vocabulary is data now, served per subject and tier by
 * `GET /api/reference` (`ReferenceData.targetGradeVocabularies`) — 0580 Core
 * publishes C-G with no A*, 0625 publishes A*-G, and a hardcoded union misled
 * both ways. `web/src/lib/grades.ts`'s `gradeRank` ranks a grade against the
 * served vocabulary in hand rather than a fixed union.
 */
export type Grade = string

/** Semantic tone used by <Chip> and status colours across both portals. */
export type Tone = "ok" | "warn" | "err" | "neutral" | "accent"

export interface QuestionResult {
  questionId: string
  awardedMarks: number
  maxMarks: number
  markerSource: MarkerSource
  confidence?: number
  feedback?: string
  matchedPointIds?: string[]
  reviewReason?: string
  topic?: string
  /**
   * The backend's own "does this question need a human" signal (mirrors
   * `QuestionResultDTO.needsTeacherReview` in `lemely/web/schemas.py`),
   * distinct from the paper-level `GradeResult.needsTeacherReview`.
   *
   * US-039: `reviewReason` alone used to mean "needs review" for every case
   * -- true for every builder except the unflagged blank
   * (`_build_blank_corrected`), which sets a `reviewReason` message purely
   * to distinguish a genuine blank from every other blank-shaped state,
   * while deliberately setting `needsTeacherReview` false. `undefined`
   * (older payloads, or callers that never set it) preserves today's
   * behaviour everywhere else -- see `lib/markingConfidence.ts` and
   * `lib/questionFilter.ts`, both of which gate on
   * `!== false` rather than requiring this field to be present.
   */
  needsTeacherReview?: boolean
  /** Mirrors `QuestionResultDTO.pendingTeacher` — whether a teacher still has
   * an open review queued for this question right now, as opposed to
   * `reviewReason`'s frozen record of why it was once flagged. `undefined`
   * on every source that has no queue to ask (a teacher-console grade, a
   * live `/student/correct` frame); only the student self-review list sets
   * it, and only there should a `false` be read as "settled".
   *
   * NOT a rename of `needsTeacherReview` above: that is the marker's flag
   * frozen at marking time, this is the live queue state. `confidenceTierFor`
   * and `isFlagged` read both. */
  pendingTeacher?: boolean
}

export interface WeakArea {
  topic: string
  marksLost: number
  marksAvailable: number
}

/** Result of an SSE job stream event (extract / grade / aggregate). */
export interface ActivityEvent {
  type: string
  message?: string
  [key: string]: unknown
}

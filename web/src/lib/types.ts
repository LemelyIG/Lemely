/*
 * Shared domain types. These mirror the Lemely Python core (lemely/core/schemas
 * — AccuracyReport, marker sources, grades) so the stubbed API layer can later
 * be swapped for the real FastAPI endpoints without touching screen code.
 */

export type PortalId = "teacher" | "student"

/** How a question was marked — the mock's 🔢 / 🤖 / ❓ legend. */
export type MarkerSource = "deterministic" | "ai" | "missing"

export type Grade = "A*" | "A" | "B" | "C" | "D" | "E" | "U"

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

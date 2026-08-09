/*
 * TS interfaces mirroring lemely/web/schemas_student.py field-for-field
 * (camelCase). Keep these in lockstep with the backend DTOs — see that module
 * for the authoritative field docs and provenance policy. Naming follows
 * authTypes.ts's convention: the Python class name with its `DTO` suffix
 * stripped (e.g. `SubjectRowDTO` -> `SubjectRow`); request/response bodies
 * that already have no `DTO` suffix in Python (`CorrectRequest`,
 * `StudentUploadResponse`) keep their Python name unchanged.
 *
 * This module is intentionally self-contained — it does not import from
 * `web/src/portals/student/data.ts` (the mock shapes these DTOs were modeled
 * on). The DTOs are the source of truth for the wire format; the mock types
 * are free to drift or be deleted once screens move off stub data.
 */

import type { Grade, MarkerSource, QuestionResult as BaseQuestionResult } from "./types"

export type VizColor = "accent" | "ok" | "warn" | "t1" | "t2" | "t3"
export type IntegrityMark = "check" | "dash" | "bang"
export type PointMark = "check" | "dot"

// ── Overview ──────────────────────────────────────────────────────────────

/** One subject card on the Overview grid (mirrors `SubjectRowDTO`). */
export interface SubjectRow {
  code: string
  name: string
  detail: string
  pct: number
  papers: number
  trend: string
  grade: string
  barColor: VizColor
  trendUp: boolean
}

/** A weak-topic accuracy bar (mirrors `WeakThreadDTO`). */
export interface WeakThread {
  topic: string
  acc: string
  width: number
  color: VizColor
}

/**
 * SVG sparkline path data for the momentum widget (mirrors `MomentumDTO`).
 * `path`/`area` are empty strings when fewer than two papers exist.
 */
export interface Momentum {
  path: string
  area: string
  lastX: string
  lastY: string
  labels: string[]
}

/** Payload for `GET /student/overview` (mirrors `OverviewDTO`). */
export interface Overview {
  studentName: string
  forecast: string
  subjects: SubjectRow[]
  weakGlobal: WeakThread[]
  momentum: Momentum
}

// ── Subject ───────────────────────────────────────────────────────────────

/** A single bar in a paper-breakdown sparkbar (mirrors `PaperBarDTO`). */
export interface PaperBar {
  value: number
  label: string
  highlight: boolean
}

/** Per-paper breakdown card (mirrors `PaperBreakdownDTO`). */
export interface PaperBreakdown {
  title: string
  sub: string
  mean: string
  boundary: string
  position: string
  positionOk: boolean
  bars: PaperBar[]
}

/**
 * A row in the subject's paper history table (mirrors `PaperHistoryRowDTO`).
 * `id` addresses the same record `GET /student/result/{paperId}` looks up.
 */
export interface PaperHistoryRow {
  id: string
  paper: string
  note: string
  marks: string
  pct: string
  grade: string
  gradeColor: VizColor
  tab: string
}

/** A tile in the topic map (mirrors `TopicTileDTO`). */
export interface TopicTile {
  name: string
  acc: string
  color: VizColor
  weak: boolean
}

/** Subject-page header block (mirrors `SubjectHeaderDTO`). */
export interface SubjectHeader {
  meta: string
  title: string
  intro: string
  forecast: string
  weightedMean: string
  weightedMeanDelta: string
}

/** Payload for `GET /student/subject/{code}` (mirrors `SubjectDTO`). */
export interface Subject {
  header: SubjectHeader
  papersBreakdown: PaperBreakdown[]
  topicMap: TopicTile[]
  paperHistory: PaperHistoryRow[]
}

// ── Paper result (flagship) ──────────────────────────────────────────────

/** One integrity-check row on the result page (mirrors `IntegrityRowDTO`). */
export interface IntegrityRow {
  mark: IntegrityMark
  color: VizColor
  label: string
  detail: string
}

/** A mark-scheme point within a theory question (mirrors `MarkPointDTO`). */
export interface MarkPoint {
  mark: PointMark
  id: string
  text: string
  got: boolean
}

/** A theory question with its marking points (mirrors `TheoryQuestionDTO`). */
export interface TheoryQuestion {
  id: string
  topic: string
  marker: string
  conf: string
  confColor: VizColor
  marks: string
  markOk: boolean
  cardWeak: boolean
  points: MarkPoint[]
  feedback: string
  feedbackTone: "ok" | "accent" | "warn"
}

/**
 * Payload for `GET /student/result/{paperId}` (mirrors `ResultDTO`).
 *
 * `theory` and `integrity` are populated only when a full per-question
 * correction is available for the paper; for history-sourced papers these
 * lists are structurally empty. Note this is distinct from the `questions`
 * key on the `POST /student/correct` SSE completion frame, which carries a
 * flatter `QuestionResult[]` shape (see `StudentCorrectFrame` below).
 */
export interface Result {
  code: string
  paper: string
  session: string
  markerLabel: string
  headline: string
  summary: string
  awarded: number
  max: number
  pct: number
  grade: string
  boundaryYear: string
  railLeft: number
  railFoot: string
  railNote: string
  theory: TheoryQuestion[]
  integrity: IntegrityRow[]
  provenance: string
}

// ── Upload + correct (self-mark) ─────────────────────────────────────────

/**
 * Payload returned by `POST /student/uploads`. `paperId` is passed back to
 * `POST /student/correct` to run the self-mark pipeline over this scan.
 */
export interface StudentUploadResponse {
  paperId: string
}

/** Request body for `POST /student/correct`. */
export interface CorrectRequest {
  paperId: string
}

/**
 * Per-question grading result carried in the `questions` key of the
 * `POST /student/correct` SSE completion frame (mirrors `QuestionResultDTO`
 * in `lemely/web/schemas.py`) — a flatter shape than `TheoryQuestion` above.
 * `types.ts` already declares a `QuestionResult` missing the two flag
 * fields the DTO carries, so this extends it rather than duplicating it.
 */
export interface QuestionResult extends BaseQuestionResult {
  plagiarismFlagged: boolean
  aiDetectionFlagged: boolean
}

// ── Standings ─────────────────────────────────────────────────────────────

/** A subject's rank line (mirrors `SubjectRankDTO`). */
export interface SubjectRank {
  code: string
  name: string
  rank: string
  color: VizColor
  papers: number
}

/** Payload for `GET /student/standings` (mirrors `StandingsDTO`). */
export interface Standings {
  subjectRanks: SubjectRank[]
  paperCount: number
  streakDays: number
}

// ── POST /student/correct SSE frames ─────────────────────────────────────
//
// The legacy onboarding types (`OnboardingRequest`, `OnboardSliderInput`,
// `StudentProfile`) were removed in P4.8 chunk A, and the legacy study-plan
// types (`StudyPlan`, `PlanSession`, `StudyPlanRequest`) in P4.10 chunk D.
// Both mirrored superseded backend surface — `POST /api/student/onboarding`
// and the `GET`/`POST /api/student/plan` pair — which chunk D then deleted
// outright (D4.22), along with their schemas and tests. The replacements are
// `/api/me/student-profile/...` (P4.3, `lib/meTypes.ts`) and
// `/api/student/study-plan/...` (P4.7 chunk C, `lib/studyPlanTypes.ts`).
// Nothing on either side is dangling now.

/**
 * SSE frames emitted by `POST /student/correct` over the shared event bus
 * (`lemely/runtime/events.py`; published from
 * `lemely/web/routers/student.py::student_correct`'s `run()` closure and,
 * transitively, from the extract/grade pipeline it calls —
 * `lemely/io/scan_metadata.py`, `lemely/io/answer_extraction.py`,
 * `lemely/io/correction_ai.py`, `lemely/io/gemini.py`).
 *
 * Unlike every DTO above, this payload is **not** a Pydantic `ApiModel`:
 * `EventBus.publish()` forwards whatever kwargs the publisher passed
 * verbatim (see `lemely/web/sse.py::_event_to_payload`), and every publisher
 * calls `bus.publish(EventType.X, some_snake_case_kwarg=...)` — so, unusually,
 * these top-level fields are **snake_case** on the wire, not camelCase. The
 * one exception is the nested `questions` array on the terminal
 * `marking_progress`/`phase: "complete"` frame, which is serialised via
 * `QuestionResultDTO.model_dump(by_alias=True)` and so IS camelCase
 * (`QuestionResult` above).
 *
 * Frame types actually observed across the full `run()` call graph:
 * `gemini_call_start`, `gemini_call_end`, `gemini_cache_hit`, `gemini_retry`,
 * `gemini_escalate`, `extraction_progress`, `marking_progress` (per-question,
 * *and* the terminal `phase: "complete"` summary), `budget_warning`,
 * `budget_exceeded`, `warning`, `error`. Kept loose (all-optional) rather
 * than a strict discriminated union, matching how `types.ts`'s `ActivityEvent`
 * is already loose.
 */
export interface StudentCorrectFrame {
  type:
    | "gemini_call_start"
    | "gemini_call_end"
    | "gemini_cache_hit"
    | "gemini_retry"
    | "gemini_escalate"
    | "extraction_progress"
    | "marking_progress"
    | "mark_scheme_progress"
    | "budget_warning"
    | "budget_exceeded"
    | "warning"
    | "error"
    | (string & {})
  /** Present on every frame published directly by `student_correct`'s `run()`. */
  paper_id?: string
  message?: string
  // marking_progress, phase: "complete" (student.py::run(), terminal frame)
  phase?: "complete" | (string & {})
  attempt_id?: string
  awarded?: number
  max_marks?: number
  grade?: Grade | string
  confidence?: number
  needs_review?: boolean
  questions?: QuestionResult[]
  // result-header fields, mirrors `_result_header_fields()` (student.py) — the
  // same fields `ResultDTO` carries on the `GET /student/result/{id}` path,
  // renamed snake_case for the SSE wire (added P2.7 step 5a, commit 9803c7b).
  code?: string
  paper?: string
  session?: string
  boundary_year?: string
  rail_left?: number
  rail_foot?: string
  pct?: number
  // marking_progress, per-question (correction_ai.py)
  question_id?: string
  marker_source?: MarkerSource
  // extraction_progress (answer_extraction.py)
  has_working?: boolean
  // gemini_call_start / gemini_call_end / gemini_cache_hit / gemini_retry / gemini_escalate
  task?: string
  model?: string
  cache_key?: string
  attempt?: number
  error?: string
  input_tokens?: number
  output_tokens?: number
  usd_cost?: number
  latency_ms?: number
  escalation_model?: string
  // budget_warning / budget_exceeded (gemini.py)
  threshold?: number
  total_usd?: number
  ceiling?: number
  // warning: scan-metadata mismatch (scan_metadata.py)
  scan_metadata?: unknown
  ms_metadata?: unknown
  [key: string]: unknown
}

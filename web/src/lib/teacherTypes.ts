/*
 * TS interfaces mirroring lemely/web/schemas_teacher.py field-for-field
 * (camelCase). Keep these in lockstep with the backend DTOs — see that module
 * for the authoritative field docs and provenance policy. Naming follows
 * studentTypes.ts's convention (itself following authTypes.ts): the Python
 * class name with its `DTO` suffix stripped (e.g. `SchemeRowDTO` ->
 * `SchemeRow`).
 *
 * Scope: only the DTOs reachable from the 7 grading-console endpoints wired
 * in this step (overview, papers list/detail, grading queue, schemes
 * list/upload, paper upload/extract/grade). The Classes and AI-quiz DTOs in
 * `schemas_teacher.py` (`ClassSummaryDTO`, `QuizPreviewDTO`, etc.) are out of
 * scope and intentionally omitted.
 *
 * This module is intentionally self-contained — it does not import from
 * `web/src/portals/teacher/data.ts` (the mock shapes these DTOs were modeled
 * on). The DTOs are the source of truth for the wire format; the mock types
 * are free to drift or be deleted once screens move off stub data.
 */

import type { MarkerSource, QuestionResult as BaseQuestionResult, WeakArea } from "./types"

/** Kind of a tracked paper, driving the grading-grid card variant (mirrors `PaperKind`). */
export type PaperKind = "graded" | "review" | "processing" | "queued"

/** Mark-scheme parse/lifecycle status (mirrors `SchemeStatus`). */
export type SchemeStatus = "parsed" | "pending" | "custom"

// ── Shared building blocks ───────────────────────────────────────────────

/**
 * A single stat card (mirrors `StatCardDTO`). `valueTone`/`footTone` are
 * presentation hints the backend derives from computed thresholds, never
 * hard-coded.
 */
export interface StatCard {
  key: string
  value: string
  unit: string | null
  foot: string | null
  valueTone: "t1" | "accent" | "err"
  footTone: "t2" | "ok" | "err"
}

/** One detected-metadata row for the grading console (mirrors `DetectedFieldDTO`). */
export interface DetectedField {
  key: string
  value: string
}

// ── Paper upload ──────────────────────────────────────────────────────────

/**
 * Response for `POST /papers/upload` (mirrors `UploadResponseDTO`). `detected`
 * is empty when metadata detection is skipped (no API key) or fails.
 */
export interface UploadResponse {
  jobId: string
  paperId: string
  detected: DetectedField[]
}

// ── Grading console ───────────────────────────────────────────────────────

/** A grading-pipeline progress step (mirrors `PipelineStepDTO`). */
export interface PipelineStep {
  label: string
  count: string
  state: "done" | "active" | "idle"
}

/** A grading batch filter tab with a live count (mirrors `BatchTabDTO`). */
export interface BatchTab {
  id: "all" | "review" | "graded" | "processing"
  label: string
  count: string
}

/**
 * One paper card in the grading grid (mirrors `PaperSummaryDTO`).
 * `pageCount` is structurally-empty (`null`) unless the pipeline recorded
 * it — no backend source exists for it yet.
 */
export interface PaperSummary {
  id: string
  name: string
  kind: PaperKind
  status: string
  awardedMarks: number | null
  maxMarks: number | null
  confidence: number | null
  needsReview: boolean
  pageCount: number | null
}

/** Response for `GET /papers` (mirrors `PaperListDTO`). */
export interface PaperList {
  papers: PaperSummary[]
  tabs: BatchTab[]
}

/**
 * Per-question grading result carried in `PaperDetailDTO.questions` (mirrors
 * `QuestionResultDTO` in `lemely/web/schemas.py`). `types.ts` already
 * declares a `QuestionResult` missing the two flag fields the DTO carries, so
 * this extends it rather than duplicating it — same approach `studentTypes.ts`
 * uses for `StudentCorrectFrame`'s `questions` field.
 */
export interface QuestionResult extends BaseQuestionResult {
  plagiarismFlagged: boolean
  aiDetectionFlagged: boolean
}

/** Response for `GET /papers/{paperId}` (mirrors `PaperDetailDTO`). */
export interface PaperDetail {
  id: string
  name: string
  kind: PaperKind
  awardedMarks: number
  maxMarks: number
  needsReview: boolean
  metadata: DetectedField[]
  pipeline: PipelineStep[]
  questions: QuestionResult[]
  weakAreas: WeakArea[]
}

/** A low-confidence flagged item in the review queue (mirrors `QueueRowDTO`). */
export interface QueueRow {
  paperId: string
  name: string
  questionId: string
  topic: string | null
  confidence: number | null
  awardedMarks: number
  maxMarks: number
}

/** Response for `GET /grading/queue` (mirrors `GradingQueueDTO`). */
export interface GradingQueue {
  rows: QueueRow[]
}

// ── Mark schemes ──────────────────────────────────────────────────────────

/** A parsed / pending / custom mark-scheme row (mirrors `SchemeRowDTO`). */
export interface SchemeRow {
  doc: string
  paper: string
  session: string
  maxMarks: number | null
  questionCount: number | null
  status: SchemeStatus
}

/** Response for `GET /schemes` (mirrors `SchemeListDTO`). */
export interface SchemeList {
  schemes: SchemeRow[]
  stats: StatCard[]
}

// ── Overview ──────────────────────────────────────────────────────────────

/** An at-risk student on the overview (mirrors `AtRiskStudentDTO`). */
export interface AtRiskStudent {
  name: string
  grade: string
  delta: number | null
  weakTopic: string | null
}

/**
 * Response for `GET /teacher/overview` (mirrors `OverviewDTO`). `retention`
 * (lesson-retention minutes) is structurally-empty — always `[]` — since no
 * backend source exists for it.
 */
export interface Overview {
  stats: StatCard[]
  atRisk: AtRiskStudent[]
  retention: number[]
}

// ── POST /papers/{id}/extract, /grade SSE frames ─────────────────────────

/**
 * SSE frames emitted by `POST /papers/{id}/extract` and
 * `POST /papers/{id}/grade` over the shared event bus
 * (`lemely/runtime/events.py`), published from the `run()` closures in
 * `lemely/web/routers/teacher.py::extract_paper` /
 * `grade_paper_endpoint` and, transitively, from
 * `lemely/web/services/grading.py::extract_answers`/`grade_paper` — which
 * fan out into `lemely/io/answer_extraction.py`, `lemely/io/correction_ai.py`,
 * and `lemely/io/gemini.py`. (`lemely/io/integrity.py`'s
 * `apply_integrity_checks`, also on the grade path, never publishes.)
 *
 * Unlike the DTOs above, this payload is **not** a Pydantic `ApiModel`:
 * `EventBus.publish()` forwards whatever kwargs the publisher passed
 * verbatim (see `lemely/web/sse.py::_event_to_payload`), so these fields are
 * **snake_case** on the wire, not camelCase — same caveat as
 * `StudentCorrectFrame` in `studentTypes.ts`.
 *
 * Frame types actually observed across both endpoints' call graphs:
 * `extraction_progress` (per answer, extract endpoint and the extract-then-grade
 * path of the grade endpoint), `marking_progress` (per question — two distinct
 * shapes, see below), `gemini_call_start`, `gemini_call_end`, `gemini_cache_hit`,
 * `gemini_retry`, `gemini_escalate`, `budget_warning`, `budget_exceeded`,
 * `warning`, `error`. Neither endpoint publishes a terminal "complete"
 * summary frame (unlike the student `/correct` pipeline) — the stream simply
 * ends at the `[DONE]` sentinel `streamActivity()` already stops on.
 *
 * `marking_progress` shape differs by path: the live `correct_paper` marking
 * loop (`correction_ai.py`) publishes `question_id`/`marker_source`/
 * `confidence`/`awarded`/`max_marks` (no `paper_id`); the cached-report
 * replay branch in `grade_paper_endpoint` (no mark scheme attached, reusing an
 * already-graded `AccuracyReport`) publishes `paper_id`/`question_id`/
 * `marker_source`/`confidence` only (no `awarded`/`max_marks`). Both shapes
 * are covered by the all-optional fields below.
 *
 * `warning` shape also differs by source: `extract_paper`'s and
 * `grade_paper_endpoint`'s own fallback branches (missing mark
 * scheme/scan/report) publish `paper_id` + `message`; the mark-scheme
 * validation warning inside `correct_paper` publishes `message` only.
 */
export interface TeacherPipelineFrame {
  type:
    | "extraction_progress"
    | "marking_progress"
    | "gemini_call_start"
    | "gemini_call_end"
    | "gemini_cache_hit"
    | "gemini_retry"
    | "gemini_escalate"
    | "budget_warning"
    | "budget_exceeded"
    | "warning"
    | "error"
    | (string & {})
  // warning (own fallback branches only — see interface doc)
  paper_id?: string
  message?: string
  // extraction_progress (answer_extraction.py)
  question_id?: string
  confidence?: number
  has_working?: boolean
  // marking_progress (correction_ai.py live loop and/or the cached-report replay)
  marker_source?: MarkerSource
  awarded?: number
  max_marks?: number
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
  [key: string]: unknown
}

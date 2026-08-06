/*
 * TS interfaces mirroring lemely/web/schemas_teacher.py field-for-field
 * (camelCase). Keep these in lockstep with the backend DTOs — see that module
 * for the authoritative field docs and provenance policy. Naming follows
 * studentTypes.ts's convention (itself following authTypes.ts): the Python
 * class name with its `DTO` suffix stripped (e.g. `SchemeRowDTO` ->
 * `SchemeRow`).
 *
 * Scope: the 7 grading-console endpoints wired in P2.8 (overview, papers
 * list/detail, grading queue, schemes list/upload, paper upload/extract/
 * grade) plus the P3.7 chunk B class-list surface (`GET /teacher/classes`,
 * `POST/PATCH/DELETE /classes/{id}` — T-01/T-02). The AI-quiz DTOs and the
 * T-03..T-06 shapes (`ClassDetailDTO`, `StudentRowDTO`, `StudentDetailDTO`,
 * `ClassAnalyticsDTO`, `AtRiskListDTO`, `QuizPreviewDTO`, etc.) are out of
 * scope for this module and intentionally omitted — chunks c/d own them.
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

// ── At-risk flags (shared by the overview, class summaries, and — from
// P3.7 chunk c/d onward — the roster, student detail, and at-risk list) ───

/**
 * Who/when/note for a flag a teacher has acknowledged (mirrors
 * `AtRiskAcknowledgementDTO`, D3.5, T-06). Present on an `AtRiskFlag` only
 * when a stored acknowledgement's evidence fingerprint still matches the
 * flag currently firing — an acknowledgement whose evidence has moved on
 * renders as `acknowledged: null`, exactly as if it had never been acked
 * (D3.5: "never a permanent mute"). `acknowledgedBy` is the acknowledging
 * teacher's id, not a resolved display name.
 */
export interface AtRiskAcknowledgement {
  acknowledgedBy: string
  acknowledgedAt: string
  note: string | null
}

/**
 * One fired D3.3 at-risk rule (mirrors `AtRiskFlagDTO`). `summary` is the
 * human-readable sentence the UI renders directly (spec §1.4: "reasons must
 * be shown, not just a red dot") — never re-derive a reason string from
 * `reason`/`evidence` client-side. `evidence` is that rule's structured
 * numbers, deliberately untyped on the wire (no frontend consumes it yet).
 */
export interface AtRiskFlag {
  reason: string
  summary: string
  evidence: Record<string, number | string | number[]>
  acknowledged: AtRiskAcknowledgement | null
}

// ── Overview ──────────────────────────────────────────────────────────────

/**
 * An at-risk student on the overview (mirrors `AtRiskStudentDTO`). `flags`
 * is the real reason-labelled D3.3 output — every student in this list has
 * at least one flag.
 */
export interface AtRiskStudent {
  name: string
  grade: string
  delta: number | null
  weakTopic: string | null
  flags: AtRiskFlag[]
}

/**
 * One recent submission across the teacher's classes (mirrors
 * `RecentActivityDTO`, T-01 item 4, D3.12). Spans papers *and* quizzes; a
 * quiz attempt has no grade by design (D3.9) — `grade` is `null` for those
 * rows and must render as an honest absence, never the student's last paper
 * grade substituted in.
 */
export interface RecentActivity {
  studentId: string
  studentName: string
  subjectCode: string
  percentage: number
  grade: string | null
  recordedAt: string
  origin: "past_paper" | "quiz" | "custom_paper"
}

/**
 * Response for `GET /teacher/overview` (mirrors `OverviewDTO`). `retention`
 * (lesson-retention minutes) is structurally-empty — always `[]` — since no
 * backend source exists for it; never render a chart fed by it.
 */
export interface Overview {
  stats: StatCard[]
  atRisk: AtRiskStudent[]
  retention: number[]
  recentActivity: RecentActivity[]
}

// ── Classes ───────────────────────────────────────────────────────────────

/**
 * One class in `GET /teacher/classes` (mirrors `ClassSummaryDTO`). `average`
 * is the mean *latest percentage* across the roster — label it exactly that
 * ("Average mark", "%"); deliberately NOT a class-level average predicted
 * grade (D3.12 — averaging letter grades invents precision the data does
 * not support). `atRiskCount`/`lastActivityAt`/`topWeakness` close the T-01
 * card / T-02 table gaps the spec names with no field to back them (D3.12);
 * an empty or history-less class reports `0`/`null`, never a placeholder.
 */
export interface ClassSummary {
  id: string
  label: string
  studentCount: number
  average: number | null
  subjectCode: string | null
  schoolId: string | null
  joinCode: string | null
  atRiskCount: number | null
  lastActivityAt: string | null
  topWeakness: string | null
}

/** Response for `GET /teacher/classes` (mirrors `ClassListDTO`). */
export interface ClassList {
  classes: ClassSummary[]
}

/** Body for `POST /classes` (mirrors `CreateClassRequestDTO`). */
export interface CreateClassRequest {
  name: string
  subjectCode?: string | null
  schoolId?: string | null
}

/** Body for `PATCH /classes/{classId}` (mirrors `UpdateClassRequestDTO`). Both fields optional. */
export interface UpdateClassRequest {
  name?: string | null
  subjectCode?: string | null
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

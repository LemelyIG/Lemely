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
 * grade), the P3.7 chunk B class-list surface (`GET /teacher/classes`,
 * `POST/PATCH/DELETE /classes/{id}` — T-01/T-02), and — added chunk c —
 * `ClassDetailDTO`/`StudentRowDTO`/`MasteryRowDTO`/`DistributionBarDTO` (T-03)
 * and the T-04 `ClassAnalyticsDTO` family (`TopicWeaknessDTO`,
 * `HeatmapCellDTO`, `GradeDistributionBucketDTO`, `TrendPointDTO`,
 * `PaperComparisonDTO`, `EngagementStatsDTO`). Chunk b's STATE.md entry
 * claimed these T-03/T-04 mirror types already existed here ("add hooks, not
 * types") — they did not; this module's own header comment said the
 * opposite ("chunks c/d own them"). Chunk c adds them now; see the phase
 * report for the discrepancy. Chunk d adds the T-05 `StudentDetailDTO`
 * family (`SubjectPredictionDTO`, `AttemptDTO`, `StudentWeaknessDTO`,
 * `StudentTrendPointDTO`, `StudentEngagementDTO`) and the T-06
 * `AtRiskListDTO` family (`AtRiskListEntryDTO`) + `AcknowledgeAtRiskRequestDTO`.
 * Quiz DTOs remain P3.8's to add.
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

// ── Class detail / roster (T-03) ────────────────────────────────────────────

/**
 * Per-topic accuracy across the class's aggregate weaknesses (mirrors
 * `MasteryRowDTO`). `national` is always `null` — no benchmark source exists
 * (never render a "vs national average" comparison from it).
 */
export interface MasteryRow {
  topic: string
  value: number
  national: number | null
  below: boolean
}

/** A grade-distribution bar (mirrors `DistributionBarDTO`). */
export interface DistributionBar {
  grade: string
  count: number
}

/**
 * A class roster row (mirrors `StudentRowDTO`, T-03). `grade` is the
 * student's latest recorded grade — render with `GradeBadge basis="predicted"`,
 * matching T-05's `SubjectPredictionDTO.predictedGrade`, the same domain
 * notion. `gradeAtRisk` (grade in D/E/U right now) and `flags` (the D3.3
 * trend/target/inactivity engine) are deliberately different signals — do
 * not conflate them or render one as the other (D3.3): a steady, active
 * D-grade student carries `gradeAtRisk: true` but no `flags`; an inactive
 * A-grade student carries `flags` but `gradeAtRisk: false`. `delta` is the
 * only trend datum this row carries — a single scalar, not a series, so it
 * cannot honestly feed `TrendSparkline` (which needs a real multi-point
 * series; faking one from one number would draw a shape the data doesn't
 * support).
 */
export interface StudentRow {
  name: string
  grade: string
  mark: string
  delta: number | null
  weakTopic: string | null
  gradeAtRisk: boolean
  studentId: string
  paperCount: number | null
  lastActiveAt: string | null
  flags: AtRiskFlag[]
}

/**
 * Response for `GET /classes/{classId}` (mirrors `ClassDetailDTO`, T-03).
 * `mastery`/`distribution` are real, roster-scoped data but are deliberately
 * NOT rendered on T-03 — they are a differently-derived per-topic accuracy /
 * grade-count computation than T-04's `ClassAnalyticsDTO` (`gradeDistribution`,
 * `topicWeaknesses`/`heatmap`), and showing both on different screens risks
 * the exact "same label, two numbers" divergence D3.3/D3.4/D3.5 each had to
 * fix once already. `stats` (class average / student count / at-risk count)
 * is rendered as the T-03 header strip; the per-topic/per-grade panels stay
 * T-04's alone.
 */
export interface ClassDetail {
  id: string
  label: string
  stats: StatCard[]
  mastery: MasteryRow[]
  distribution: DistributionBar[]
  students: StudentRow[]
  subjectCode: string | null
  schoolId: string | null
  joinCode: string | null
  atRiskCount: number | null
  lastActivityAt: string | null
  topWeakness: string | null
}

/** One enrolled student's identity (mirrors `RosterEntryDTO`). */
export interface RosterEntry {
  studentId: string
  displayName: string
}

/** Body for `POST /classes/{classId}/enroll` (mirrors `EnrollStudentRequestDTO`). */
export interface EnrollStudentRequest {
  studentId: string
}

// ── Class analytics (T-04) ──────────────────────────────────────────────────

/**
 * One topic ranked by class-wide marks lost, most-lost-first (mirrors
 * `TopicWeaknessDTO`). `studentIds` backs "click a weakness -> the students
 * affected" without a second round trip.
 */
export interface TopicWeakness {
  topic: string
  lostMarks: number
  maximumMarks: number
  accuracy: number
  studentIds: string[]
}

/**
 * One (topic, student) heatmap cell (mirrors `HeatmapCellDTO`). `accuracy` is
 * `null` when the student has no persisted weak-area entry for this topic —
 * this is NOT the same as a 0% score (a student who never attempted the
 * topic vs. one who attempted and lost every mark look identical in what's
 * persisted, per the core module's honesty note) and must render as a
 * distinct "no data" cell, never as 0%.
 */
export interface HeatmapCell {
  topic: string
  studentId: string
  accuracy: number | null
}

/** Count of students on one grade, full ladder incl. zero counts (mirrors `GradeDistributionBucketDTO`). */
export interface GradeDistributionBucket {
  grade: string
  count: number
}

/** One point in the cohort mean-percentage-over-time series (mirrors `TrendPointDTO`). */
export interface TrendPoint {
  timestamp: string
  label: string
  meanPercentage: number
  sampleSize: number
}

/** Cohort stats for one paper identity (mirrors `PaperComparisonDTO`). */
export interface PaperComparison {
  paperId: string
  subjectCode: string
  paperNumber: number
  paperVariant: number
  meanPercentage: number
  attemptCount: number
  studentCount: number
}

/** Submission-activity stats (mirrors `EngagementStatsDTO`). */
export interface EngagementStats {
  submissionsLast7Days: number
  submissionsLast30Days: number
  activeStudentsLast7Days: number
  activeStudentsLast30Days: number
  neverActiveCount: number
  medianDaysSinceLastSubmission: number | null
}

/** Response for `GET /classes/{classId}/analytics` (mirrors `ClassAnalyticsDTO`, T-04). */
export interface ClassAnalytics {
  topicWeaknesses: TopicWeakness[]
  heatmap: HeatmapCell[]
  gradeDistribution: GradeDistributionBucket[]
  trend: TrendPoint[]
  paperComparison: PaperComparison[]
  engagement: EngagementStats
}

// ── Student detail, teacher view (T-05) ─────────────────────────────────────

/**
 * One subject's predicted grade for this student (mirrors `SubjectPredictionDTO`).
 * `predictedGrade` is the student's latest recorded grade for the subject —
 * the same domain notion of "predicted grade" `lemely.core.at_risk` already
 * uses for its below-target rule (`history.records[-1].grade`), not a second,
 * differently-computed forecast — render with `GradeBadge basis="predicted"`,
 * matching `StudentRow.grade`'s convention on T-03.
 */
export interface SubjectPrediction {
  subjectCode: string
  predictedGrade: string
  latestPercentage: number
  paperCount: number
}

/** One recorded paper attempt, newest first (mirrors `AttemptDTO`). Quiz
 * attempts are excluded — grade-bearing (past-paper) records only, per
 * D3.9; see the router's `_student_detail_dto` docstring. */
export interface Attempt {
  paperId: string
  subjectCode: string
  paperNumber: number
  paperVariant: number
  awardedMarks: number
  maximumMarks: number
  percentage: number
  grade: string
  recordedAt: string
}

/** One weak topic with its evidence (mirrors `StudentWeaknessDTO`).
 * Deliberately unfiltered by origin (quiz or paper) — a weakness is a
 * weakness whatever revealed it (unlike `attempts`/`trend`). */
export interface StudentWeakness {
  topic: string
  lostMarks: number
  maximumMarks: number
  accuracy: number
  questionIds: string[]
}

/** One point in this student's own percentage-over-time series (mirrors
 * `StudentTrendPointDTO`) — grade-bearing attempts only, chronological. */
export interface StudentTrendPoint {
  recordedAt: string
  percentage: number
}

/** This student's own activity stats (mirrors `StudentEngagementDTO`). */
export interface StudentEngagement {
  totalPapers: number
  lastActiveAt: string | null
  daysSinceLastSubmission: number | null
}

/**
 * Response for `GET /teacher/students/{studentId}` (mirrors `StudentDetailDTO`,
 * T-05). `atRiskFlags` is populated through the same `_at_risk_flag_dto`
 * helper T-01/T-06 use, so `acknowledged` reads identically everywhere a flag
 * for this student appears (D3.5).
 *
 * **This DTO carries no integrity-signal field at all** — not an
 * always-empty stub, an absent field. A persisted history record has only
 * totals/weak-areas/metadata, never the per-question answers the
 * plagiarism/AI-content checks need (those run only in the live, in-process
 * `/papers/{id}/grade` flow — see the router's `teacher_student_detail`
 * docstring, D3.4). Do not render a panel for it and do not add a field here
 * to make one possible; that is a backend change out of this screen's scope.
 */
export interface StudentDetail {
  studentId: string
  displayName: string
  subjects: SubjectPrediction[]
  attempts: Attempt[]
  weaknesses: StudentWeakness[]
  trend: StudentTrendPoint[]
  isAtRisk: boolean
  atRiskFlags: AtRiskFlag[]
  engagement: StudentEngagement
}

// ── At-risk list (T-06) ──────────────────────────────────────────────────────

/**
 * One flagged student across the caller's classes (mirrors
 * `AtRiskListEntryDTO`). `grade` is the student's latest *paper* grade
 * (matching the overview's at-risk rows exactly) and is `""` when the
 * student has only quiz activity — render as an honest absence, never a
 * placeholder grade.
 */
export interface AtRiskListEntry {
  studentId: string
  displayName: string
  classId: string
  className: string
  grade: string
  flags: AtRiskFlag[]
}

/**
 * Response for `GET /teacher/at-risk` (mirrors `AtRiskListDTO`, T-06).
 * **Already sorted server-side by severity** before this ever reaches the
 * client — `_at_risk_severity_key` in `lemely/web/routers/teacher.py`: flag
 * count descending, then worst (furthest-down-`GRADE_ORDER`) grade first.
 * The screen mirrors this identical two-key ordering client-side only so its
 * "Severity" column stays re-sortable after a teacher sorts by something
 * else and clicks back — it is a UI convention matching the backend's own
 * documented definition, never an invented numeric score presented as
 * engine output.
 */
export interface AtRiskList {
  students: AtRiskListEntry[]
}

/**
 * Body for `POST /teacher/at-risk/{studentId}/acknowledge` (mirrors
 * `AcknowledgeAtRiskRequestDTO`, T-06). `reason` must name a rule currently
 * firing for this student — the backend 422s otherwise (D3.5); `note` is
 * optional and teacher-facing only, never shown to the student/parent.
 */
export interface AcknowledgeAtRiskRequest {
  reason: string
  note?: string | null
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

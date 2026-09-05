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
 * P3.8 chunk b adds the T-07/T-08 `schemas_review.py` family (`ReviewQueueItem`,
 * `ReviewItemDetail`, `ReviewBreakdown`, `ResolveReviewRequest`,
 * `DismissReviewRequest`, `BulkApproveRequest`/`Response`/`Skip`) and removes
 * `QueueRow`/`GradingQueue` (mirrors of the old `GET /grading/queue` DTOs) —
 * only the old `Review.tsx`, now replaced by the real T-07/T-08, consumed
 * them; `Grading.tsx` (the P2 console) uses `PaperList`/`PaperDetail`
 * instead. P3.8 chunk c adds the T-09 quiz-builder family
 * (`lemely/web/schemas_quiz.py`, `GET`/`POST /api/teacher/quizzes/*`):
 * `QuizQuestion`, `QuizSummary`, `QuizList`, `QuizDetail`,
 * `CreateQuizRequest`, `UpdateQuizDraftRequest`, `SetQuizStatusRequest`,
 * `GenerateQuizQuestionsResponse`, `CreateQuizAssignmentRequest`,
 * `QuizAssignment`, `QuizAssignmentList`, `QuizPoolCount`. Deliberately
 * excludes the T-10 results family (`QuizAssignmentResultsDTO` and its
 * nested DTOs) — that is a later phase's screen to build. Announcement
 * endpoints remain a later P3.8 chunk's to add.
 *
 * This module is intentionally self-contained — it does not import from
 * `web/src/portals/teacher/data.ts` (the mock shapes these DTOs were modeled
 * on). The DTOs are the source of truth for the wire format; the mock types
 * are free to drift or be deleted once screens move off stub data.
 */

import type { QuestionResult as BaseQuestionResult, WeakArea } from "./types"

/**
 * Kind of a tracked paper, driving the grading-grid card variant (mirrors
 * `PaperKind`). `queued` means "waiting for the grading worker", `processing`
 * means "being marked right now", and `failed` is terminal — a run that can
 * never produce marks (it crashed, or no mark scheme could be resolved).
 * `failed` exists because leaving such a paper at `queued` is indistinguishable
 * from one still waiting its turn, which was the unexplained "queued forever"
 * state D6.13 removes.
 */
export type PaperKind = "graded" | "review" | "processing" | "queued" | "failed"

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
 *
 * `name` is the detected-paper label (`Paper 3 V1 May/June 2020 - 2026-08-12`)
 * once the backend has read the scan's metadata, and the teacher's own uploaded
 * filename until then. `error` is populated only when `kind === "failed"`.
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
  error: string | null
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

/**
 * Response for `GET /papers/{paperId}` (mirrors `PaperDetailDTO`).
 *
 * Served for papers that have *not* finished grading too, which is why the mark
 * totals are nullable. That route used to 409 until a report existed, so the
 * console's Pipeline panel had nothing to render after a page reload and the
 * stepper simply vanished mid-run (D6.13). `questions`/`weakAreas` stay empty
 * until there is a real correction behind them; `pipeline` carries live job
 * progress, so it is the one thing that *does* survive a refresh.
 */
export interface PaperDetail {
  id: string
  name: string
  kind: PaperKind
  awardedMarks: number | null
  maxMarks: number | null
  needsReview: boolean
  error: string | null
  metadata: DetectedField[]
  pipeline: PipelineStep[]
  questions: QuestionResult[]
  weakAreas: WeakArea[]
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
  subjectName: string | null
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
  subjectName: string | null
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

// ── Class invite codes (D7.3, spec §1.2 / BUILD/BLOCKERS.md B8) ────────────

/**
 * A freshly minted, single-use class invite code (mirrors `InviteCodeDTO`,
 * `lemely/web/schemas_invites.py` — not `schemas_teacher.py`, an exception
 * to this file's header rule, because `POST /school/classes/{classId}/
 * invite-code` is where a class's self-enrolment capability is handed out a
 * second way, alongside `ClassDetail.joinCode` above). `POST
 * /school/classes/{classId}/invite-code` takes no body (`classId` is a path
 * segment and the caller's identity comes off the bearer token), so unlike
 * the seat invite's `MintSeatInviteRequest` (`adminTypes.ts`) there is no
 * matching request interface here. `schoolId` is always `null` for a class
 * invite in practice; kept in the interface anyway because this is the same
 * wire shape `mint_seat_invite_code` returns and the two response DTOs are
 * deliberately one Python class (`InviteCodeDTO`) so they cannot drift apart
 * on the backend, a guarantee a narrower frontend type would quietly lose.
 */
export interface ClassInviteCode {
  code: string
  role: "student" | "teacher"
  schoolId: string | null
  classId: string | null
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

// ── Review queue (T-07 queue list, T-08 remark) ─────────────────────────────

/**
 * One T-07 queue row (mirrors `ReviewQueueItemDTO`). `reason` is a
 * `ReviewReason` value (`low_confidence` / `plagiarism_flag` /
 * `ai_detection_flag` / `manual`) and `status` a `ReviewStatus` value
 * (`open` / `resolved` / `dismissed`) — both plain strings on the wire, not
 * union-typed here, matching every other enum-backed string field elsewhere
 * in this file (e.g. `AtRiskFlag.reason`). `questionResultId`/`questionId`
 * are `null` for a review item with no underlying `QuestionResult` (see
 * `ReviewItemDetail`'s doc) — `aiAwardedMarks`/`maximumMarks`/
 * `confidenceScore` are `null` in the same case. `subjectCode`/`paperNumber`/
 * `paperVariant`/`sessionMonth`/`sessionYear` are all `null` together for a
 * quiz-originated item (a quiz `Attempt` carries no paper identity) — render
 * as "Quiz question", never a blank paper-identity line.
 */
export interface ReviewQueueItem {
  itemId: string
  attemptId: string
  questionResultId: string | null
  studentId: string
  studentDisplayName: string
  classId: string
  className: string
  subjectCode: string | null
  paperNumber: number | null
  paperVariant: number | null
  sessionMonth: string | null
  sessionYear: number | null
  questionId: string | null
  reason: string
  status: string
  createdAt: string
  waitingHours: number
  aiAwardedMarks: number | null
  maximumMarks: number | null
  confidenceScore: number | null
}

/** Response for `GET /teacher/review` (mirrors `ReviewQueueListDTO`). Already
 * ordered oldest-first by the backend (`ReviewQueueItem.created_at` asc) —
 * the longest-waiting item is the highest priority, so T-07 renders this
 * order directly rather than re-sorting client-side. */
export interface ReviewQueueList {
  items: ReviewQueueItem[]
}

/**
 * A teacher-supplied method/accuracy breakdown (mirrors `ReviewBreakdownDTO`).
 * Deliberately not derived from the mark scheme's M/A/B point types — those
 * live in the parsed scheme, not on the persisted `QuestionResult` — every
 * field here is exactly what the teacher typed, nothing computed.
 */
export interface ReviewBreakdown {
  methodMarks: number | null
  accuracyMarks: number | null
  otherMarks: number | null
  notes: string | null
}

/**
 * Response for `GET /teacher/review/{itemId}` (mirrors `ReviewItemDetailDTO`,
 * T-08). Extends `ReviewQueueItem` with the question content, AI marking
 * evidence, and any recorded teacher override.
 *
 * **`studentAnswer` is Lemely's transcription of the student's handwriting,
 * not the scan image; `expectedAnswer`/`matchedPointIds` are the mark
 * scheme's expected answer and the identifiers of the points the AI matched
 * — not the scheme's prose.** Neither the original scan crop nor the mark
 * scheme's extract text is persisted anywhere in this product (D3.14 §1,
 * `ReviewItemDetailDTO`'s own docstring) — T-08 must label these as exactly
 * what they are and say plainly that the scan/scheme extract don't exist,
 * never render a placeholder image or reconstruct scheme prose from the
 * point ids (inventing precision, UI-spec §1.4).
 */
export interface ReviewItemDetail extends ReviewQueueItem {
  studentAnswer: string | null
  expectedAnswer: string | null
  topic: string | null
  matchedPointIds: string[]
  feedback: string | null
  markerSource: string | null
  reviewReason: string | null
  isOverridden: boolean
  teacherAwardedMarks: number | null
  teacherNote: string | null
  teacherBreakdown: ReviewBreakdown | null
  overriddenBy: string | null
  overriddenAt: string | null
  resolutionNote: string | null
  resolvedBy: string | null
  resolvedAt: string | null
}

/**
 * Body for `POST /teacher/review/{itemId}/resolve` (mirrors
 * `ResolveReviewRequestDTO`). Omitting `overrideMarks` accepts the AI mark
 * unchanged and closes the item — `note` in that path is recorded as an
 * **internal** resolution note only. Supplying `overrideMarks` records a
 * teacher correction on the underlying `QuestionResult`; `note` in that path
 * becomes `teacherNote` on the corrected result — the "note to the student"
 * the UI spec asks T-08 for. There is no notification/delivery path for
 * either case yet (no consumer renders `teacherNote` on the student side and
 * no push exists — see `ReviewItem.tsx`'s module doc); the copy must not
 * claim the student is notified.
 */
export interface ResolveReviewRequest {
  overrideMarks?: number | null
  breakdown?: ReviewBreakdown | null
  note?: string | null
}

/** Body for `POST /teacher/review/{itemId}/dismiss` (mirrors
 * `DismissReviewRequestDTO`). Dismisses an integrity flag; `note` is an
 * internal record only. Never touches the underlying `QuestionResult` — no
 * student-visible record survives a dismissal (see `ReviewService.dismiss`'s
 * docstring). Restricted server-side to `plagiarism_flag`/`ai_detection_flag`
 * items — a 422 otherwise. */
export interface DismissReviewRequest {
  note?: string | null
}

/** Body for `POST /teacher/review/bulk-approve` (mirrors
 * `BulkApproveRequestDTO`). */
export interface BulkApproveRequest {
  itemIds: string[]
}

/** One id bulk-approve declined to touch, and why (mirrors
 * `BulkApproveSkipDTO`). `reason` is one of `not_found` / `forbidden` /
 * `already_closed` — a plain machine code, not prose; the screen maps it to
 * a human sentence. */
export interface BulkApproveSkip {
  itemId: string
  reason: string
}

/** Response for `POST /teacher/review/bulk-approve` (mirrors
 * `BulkApproveResponseDTO`). Skip-and-report, not all-or-nothing — a caller
 * must render `skipped`, never assume every requested id succeeded because
 * the call itself didn't throw. */
export interface BulkApproveResponse {
  approved: string[]
  skipped: BulkApproveSkip[]
}

// ── Quiz builder (T-09) ──────────────────────────────────────────────────

/**
 * One materialized quiz question — the frozen snapshot (mirrors
 * `QuizQuestionDTO`, `docs/quiz-model.md` §1.5). The question **text is
 * copied, not referenced** — `questionBankId` is provenance only, so a bank
 * row edited/deactivated later never changes what a student already
 * answered. `status` is `"included"` or `"removed"` — removed rows are kept,
 * not deleted, and still appear here (the curation audit trail): render
 * included ones as the quiz, removed ones only in a separate "removed"
 * list, never silently drop them from existence and never present them as
 * part of the live quiz either. `difficulty` is a `Band` value
 * (`"foundation"` / `"standard"` / `"challenge"`) — a plain string on the
 * wire like every other enum-backed field in this file.
 */
export interface QuizQuestion {
  id: string
  questionBankId: string | null
  questionRef: string
  position: number
  status: string
  replacedById: string | null
  topic: string | null
  difficulty: string
  questionType: string
  prompt: string
  modelAnswer: string | null
  markSchemePoints: string[]
  mcqOptions: string[] | null
  mcqAnswer: string | null
  totalMarks: number
}

/**
 * One quiz, draft or otherwise — the builder's resumable state (mirrors
 * `QuizSummaryDTO`, §1.4). `status` is one of `"draft"` / `"assigned"` /
 * `"closed"` / `"archived"`; the lifecycle never runs backwards, and every
 * field above is only PATCHable while `status === "draft"` (a non-draft
 * quiz opens read-only — editing it while students may be mid-attempt is
 * exactly what the backend 422s). `targetGrade` is a `Grade` member (see
 * `lib/types.ts`) or `null` while step 3 is untargeted — validated at the
 * API boundary, not re-validated client-side. `poolSource` is one of
 * `"past_paper"` / `"generated"` / `"teacher_upload"`, or `null` while step 4
 * is undecided. **`subjectCode` has no corresponding `UpdateQuizDraftRequest`
 * field — it is fixed at creation** (`CreateQuizRequest`, entered on the
 * quiz-list screen, not in the builder) and the builder's step 1 must render
 * it read-only, never as an editable input the PATCH would silently ignore.
 * `builderStep` (1-6) is advisory only — it drives where a resumed draft
 * reopens, never an authorization check (the server enforces every guard
 * above independent of it).
 */
export interface QuizSummary {
  id: string
  subjectCode: string
  title: string
  status: string
  targetGrade: string | null
  includedTopics: string[]
  poolSource: string | null
  requestedCount: number | null
  timeLimitMinutes: number | null
  builderStep: number
  questionCount: number
}

/** Response for `GET /teacher/quizzes` (mirrors `QuizListDTO`). The
 * caller's owned quizzes, newest first. */
export interface QuizList {
  quizzes: QuizSummary[]
}

/** Response for `GET /teacher/quizzes/{quizId}` (mirrors `QuizDetailDTO`) —
 * one owned quiz plus every materialized question row (included and
 * removed). */
export interface QuizDetail {
  quiz: QuizSummary
  questions: QuizQuestion[]
}

/**
 * Body for `POST /teacher/quizzes` (mirrors `CreateQuizRequestDTO`) —
 * step 1's two required fields, collected on the quiz-list screen before
 * the builder ever opens (D3.15). Class/due-date/closes-at are deliberately
 * NOT collected here or anywhere in step 1: `quizzes` has no such columns —
 * they belong to step 6's `quiz_assignments` row.
 */
export interface CreateQuizRequest {
  subjectCode: string
  title: string
}

/**
 * Body for `PATCH /teacher/quizzes/{quizId}` (mirrors
 * `UpdateQuizDraftRequestDTO`) — every field optional; an omitted field (or
 * an explicit `null`, per the DTO's own docstring — there is no separate
 * "clear this field" sentinel here, unlike `SaveAnswerRequestDTO`) leaves
 * the stored value untouched. 422 when the quiz is not currently a draft.
 */
export interface UpdateQuizDraftRequest {
  title?: string | null
  targetGrade?: string | null
  includedTopics?: string[] | null
  poolSource?: string | null
  requestedCount?: number | null
  timeLimitMinutes?: number | null
  builderStep?: number | null
}

/** Body for `POST /teacher/quizzes/{quizId}/status` (mirrors
 * `SetQuizStatusRequestDTO`) — one of `"draft"` / `"assigned"` / `"closed"` /
 * `"archived"`, never backwards. **Not** used to move a quiz from `draft` to
 * `assigned` — `create_assignment` already does that transition itself; this
 * endpoint is only for closing/archiving. */
export interface SetQuizStatusRequest {
  status: string
}

/**
 * Response for `POST /teacher/quizzes/{quizId}/questions/generate` (mirrors
 * `GenerateQuizQuestionsResponseDTO`). **Additive** — calling again after
 * raising `requestedCount` tops the set up, never replaces it, so `created`
 * may legitimately be `[]` when the quiz already has its requested count.
 * `shortfall` is `null` when nothing is short, or a band -> deficit map
 * naming which constraint to loosen — render verbatim, never rounded or
 * padded into a plausible-looking count.
 */
export interface GenerateQuizQuestionsResponse {
  created: QuizQuestion[]
  shortfall: Record<string, number> | null
}

/**
 * Body for `POST /teacher/quizzes/{quizId}/assignments` (mirrors
 * `CreateQuizAssignmentRequestDTO`) — step 6. `dueAt`/`closesAt` are
 * ISO-8601 tz-aware datetime strings (the router 422s a naive one) or
 * omitted. The backend 422s assigning a quiz with zero `included`
 * questions, a `closesAt` earlier than `dueAt`, or the same class twice —
 * every case must render as a real error, not be silently swallowed.
 */
export interface CreateQuizAssignmentRequest {
  classId: string
  dueAt?: string | null
  closesAt?: string | null
}

/**
 * One assignment of a quiz to a class (mirrors `QuizAssignmentDTO`, §1.6).
 * `rosterSize`/`submissionCounts` are read live at request time, never a
 * frozen snapshot. **Creating this already transitions a `draft` quiz to
 * `assigned` server-side — the caller must never also call
 * `SetQuizStatusRequest` afterwards.**
 */
export interface QuizAssignment {
  id: string
  classId: string
  className: string
  assignedAt: string
  dueAt: string | null
  closesAt: string | null
  rosterSize: number
  submissionCounts: Record<string, number>
}

/** Response for `GET /teacher/quizzes/{quizId}/assignments` (mirrors
 * `QuizAssignmentListDTO`). */
export interface QuizAssignmentList {
  assignments: QuizAssignment[]
}

/**
 * Response for `GET /teacher/quizzes/pool-count` (mirrors `QuizPoolCountDTO`,
 * §2, T-09 steps 3/4). `byBand` is exactly the allocation the builder itself
 * will produce for `(targetGrade, requestedCount)` — safe to render as "the
 * real mix", never a hardcoded table. `shortfall` is `null` when nothing is
 * short, or a band -> deficit map. `message` carries the exact
 * honest-degradation wording (D3.7) when `source="past_paper"` matches zero
 * rows for the subject — render it verbatim, never invent a caption in its
 * place. **`question_bank` ships empty (D3.7)**, so a first-time teacher's
 * `past_paper` count is genuinely 0 for every subject — this is the expected
 * first-run state this screen must render plainly, not a bug to hide.
 */
export interface QuizPoolCount {
  matching: number
  requested: number
  byBand: Record<string, number>
  shortfall: Record<string, number> | null
  difficultyEstimated: boolean
  message: string | null
}

// ── T-10 quiz results ────────────────────────────────────────────────────
// Mirrors `lemely/web/schemas_quiz.py`'s results family. Every panel below is
// a projection over ONE server-side load of the assignment's submissions
// (`QuizResultsService`, §4.6), so no two can disagree — never re-derive one
// of these numbers client-side from another.

/**
 * Completion against the **live** roster (mirrors `QuizCompletionDTO`).
 * `completionRate` is `null` for an empty roster, not 0 — 0/0 is not 0%, and
 * rendering it as 0% would read as "nobody has done it" when the truth is
 * "there is nobody to do it". `offRosterSubmissionCount` is work handed in by
 * students who have since left the class: excluded from every panel because
 * the denominator is the live roster, but reported rather than silently
 * dropped (D3.10). **Do not "simplify" it away or fold it into the counts.**
 */
export interface QuizCompletion {
  rosterSize: number
  completedCount: number
  completionRate: number | null
  statusCounts: Record<string, number>
  offRosterSubmissionCount: number
}

/**
 * One ten-point band of the score distribution (mirrors `QuizScoreBucketDTO`).
 * Deliberately a **percentage** distribution, not a grade one: a quiz has no
 * grade boundaries to bucket by (§4.6 rule (b), D3.9). The top band is
 * inclusive of 100.
 */
export interface QuizScoreBucket {
  lower: number
  upper: number
  studentCount: number
}

/**
 * One question's class-wide performance (mirrors `QuizQuestionAnalysisDTO`),
 * in the quiz's display order. Every mark is an `effective_marks` sum, so a
 * teacher's override reads here exactly as it reads on the student's screen
 * (§4.6 rule (a)). `averageMarks`/`accuracy` are `null` — never 0 — when
 * nobody has been marked on the question yet; render that as "not yet
 * answered", never as 0%.
 */
export interface QuizQuestionAnalysis {
  questionRef: string
  position: number
  prompt: string
  topic: string | null
  difficulty: string
  totalMarks: number
  answeredCount: number
  averageMarks: number | null
  accuracy: number | null
  fullMarksCount: number
  zeroMarksCount: number
  needsReviewCount: number
  overriddenCount: number
}

/**
 * One roster student's result (mirrors `QuizStudentResultDTO`), present
 * whether or not they submitted. Mark fields are `null` until marking lands;
 * `markingError` is set when marking failed, so a `submitted`-but-unmarked row
 * is visibly explained rather than silently empty — render it, do not treat a
 * null mark as a zero.
 */
export interface QuizStudentResult {
  studentId: string
  displayName: string
  status: string
  submittedAt: string | null
  markedAt: string | null
  awardedMarks: number | null
  maximumMarks: number | null
  percentage: number | null
  confidenceBand: string | null
  needsTeacherReview: boolean
  marksByQuestion: Record<string, number>
  markingError: string | null
}

/**
 * Response for
 * `GET /teacher/quizzes/{quizId}/assignments/{assignmentId}/results`
 * (mirrors `QuizAssignmentResultsDTO`). Aggregated per **assignment** — one
 * class — never per quiz (§1.6): a quiz assigned to two classes has two sets
 * of results, and averaging them would describe neither cohort.
 */
export interface QuizAssignmentResults {
  assignment: QuizAssignment
  quizTitle: string
  subjectCode: string
  questionCount: number
  totalMarks: number
  completion: QuizCompletion
  averagePercentage: number | null
  medianPercentage: number | null
  scoreDistribution: QuizScoreBucket[]
  questionAnalysis: QuizQuestionAnalysis[]
  students: QuizStudentResult[]
  topicWeaknesses: TopicWeakness[]
}

// ── T-12 announcements ───────────────────────────────────────────────────
// Mirrors `lemely/web/schemas_announcements.py` (P3.8 chunk a).

/**
 * Body for `POST /teacher/announcements`. **Exactly one of `classIds` /
 * `schoolWide` may be given** — neither is a 422 and so is *both*, because the
 * two audiences overlap and a combined request would deliver twice to a
 * student enrolled in a class of that school. The rule lives in the service,
 * so the composer must not offer a UI state that sends both. `schoolId` is
 * required whenever `schoolWide` is true (a school_admin can administer
 * several schools, so the flag alone does not say which).
 *
 * `publishAt` is **stored but never read** — no scheduler exists and delivery
 * is Phase 5's. Label it honestly; never imply it will fire.
 */
export interface AnnouncementCreateRequest {
  title: string
  body: string
  classIds?: string[]
  schoolWide?: boolean
  schoolId?: string | null
  publishAt?: string | null
}

/** One announcement row, exactly as stored (mirrors `AnnouncementDTO`) — no
 * derived or enriched fields, so `classId`/`schoolId` are raw ids the client
 * must resolve against its own class list to name. */
export interface Announcement {
  announcementId: string
  authorId: string
  schoolId: string | null
  classId: string | null
  title: string
  body: string
  publishAt: string | null
  createdAt: string
}

/** Response for `POST /teacher/announcements` — every row the fan-out created.
 * Fan-out is **all-or-nothing**: a teacher owning 9 of 10 targeted classes
 * gets a 403 and zero rows, never a partial send. */
export interface AnnouncementCreateResponse {
  announcements: Announcement[]
}

/** Response for `GET /teacher/announcements` (author-scoped, newest first). */
export interface AnnouncementList {
  announcements: Announcement[]
}

/*
 * Pure data + logic for the S-01/S-02 onboarding wizard. No React, no DOM —
 * this is what `web/tests/unit/onboarding.test.ts` exercises directly
 * (`vitest.config.ts` runs the unit suite in a Node environment with no
 * jsdom/@testing-library, D3.20 — component behaviour is Playwright's job,
 * not this file's; this file is the pure logic a browser test can't
 * cheaply pin, especially the D4.5 skip-produces-no-value rule).
 *
 * Curriculum data (subject names, paper numbers/names, syllabus topic
 * labels) is transcribed from the same backend sources already verified
 * against the official CAIE syllabus PDFs — `lemely/data/paper_timing.json`
 * (paper structure) and `lemely/data/syllabus_topics.json` (topic
 * vocabulary, D4.4) — rather than invented here. There is no student-facing
 * route that serves this structural data (`/api/me/*` only holds the
 * student's own answers), so it is mirrored once, the same way
 * `GRADE_ORDER` is already duplicated as a local const in three teacher
 * screens (`Quizzes.tsx`, `ClassRoster.tsx`, `AtRiskList.tsx`) rather than
 * fetched.
 */

import type { EnrolmentUpsert } from "@/lib/meTypes"

// ── Curriculum data (MISSION §1 scopes this phase to exactly these three
// subjects; "more subjects coming" is rendered explicitly in S-01 so the
// absence of a fourth card doesn't read as a bug) ──────────────────────────

export interface SubjectPaper {
  number: number
  name: string
}

export interface SupportedSubject {
  code: string
  name: string
  papers: SubjectPaper[]
  /** Up to 3 top-level P4.2 topic labels ("<code> <name>") this subject's
   * S-02 confidence step asks about — the first 3 in syllabus order,
   * transcribed verbatim from `syllabus_topics.json`, never invented. */
  confidenceTopics: string[]
}

export const SUPPORTED_SUBJECTS: SupportedSubject[] = [
  {
    code: "0625",
    name: "Physics",
    papers: [
      { number: 1, name: "Multiple Choice (Core)" },
      { number: 2, name: "Multiple Choice (Extended)" },
      { number: 3, name: "Theory (Core)" },
      { number: 4, name: "Theory (Extended)" },
      { number: 5, name: "Practical Test" },
      { number: 6, name: "Alternative to Practical" },
    ],
    confidenceTopics: ["1 Motion, forces and energy", "2 Thermal physics", "3 Waves"],
  },
  {
    code: "0580",
    name: "Mathematics",
    papers: [
      { number: 1, name: "Non-calculator (Core)" },
      { number: 2, name: "Non-calculator (Extended)" },
      { number: 3, name: "Calculator (Core)" },
      { number: 4, name: "Calculator (Extended)" },
    ],
    confidenceTopics: ["1 Number", "2 Algebra and graphs", "3 Coordinate geometry"],
  },
  {
    code: "0606",
    name: "Additional Mathematics",
    papers: [
      { number: 1, name: "Non-calculator" },
      { number: 2, name: "Calculator" },
    ],
    confidenceTopics: ["1 Functions", "2 Quadratic functions", "3 Factors of polynomials"],
  },
]

/** Mirrors `lemely.db.models.enums.QualificationLevel`. Re-exported from the
 * shared table so there is exactly one source of truth for it. */
export { QUALIFICATION_LEVELS } from "@/lib/qualificationLevels"

/** Mirrors `lemely.db.models.enums.SESSION_MONTH_LABELS`. */
export const SESSION_MONTHS: { value: string; label: string }[] = [
  { value: "may_june", label: "May/June" },
  { value: "oct_nov", label: "Oct/Nov" },
  { value: "feb_mar", label: "Feb/Mar" },
  { value: "specimen", label: "Specimen" },
]

/** Mirrors `lemely.core.history.GRADE_ORDER`, already duplicated as a local
 * const in three teacher screens — same precedent, not a new pattern. */
export const GRADE_ORDER = ["A*", "A", "B", "C", "D", "E", "U"]

export const WEEKLY_HOURS_MIN = 0
/** UI-only cap, tighter than the backend's 0..80 validation ceiling — 40
 * covers every realistic weekly-study answer; a student's own text isn't
 * lost by capping the slider (the backend bound still applies server-side). */
export const WEEKLY_HOURS_MAX = 40

export const CONFIDENCE_MIN = 1
export const CONFIDENCE_MAX = 5

/**
 * Which subject's placement invite (S-03) to send the student to when they
 * finish S-02, or `null` if they enrolled in none — in which case there is
 * no placement test to invite them into and the caller sends them to S-06.
 *
 * Deliberately NOT `Object.keys(drafts)[0]`. The drafts object is keyed by
 * syllabus code, and JS enumerates integer-like string keys first, in
 * ascending numeric order, ahead of every other key's insertion order. All
 * three of today's codes have a leading zero (`0625`/`0580`/`0606`) and so
 * are not integer-like — insertion order happens to survive, which is
 * exactly what makes the bug invisible now and live the day a code without
 * a leading zero is added. Ordering by the catalogue instead means the
 * student is sent to the first subject *as presented to them in S-01*,
 * which is a rule that stays true whatever the codes look like.
 */
export function placementInviteSubject(enrolledCodes: readonly string[]): string | null {
  const enrolled = new Set(enrolledCodes)
  return SUPPORTED_SUBJECTS.find((subject) => enrolled.has(subject.code))?.code ?? null
}

// ── S-01 subject/paper/target selection ─────────────────────────────────

export interface SubjectDraft {
  subjectCode: string
  papers: ReadonlySet<number>
  targetGrade: string | null
  sessionMonth: string | null
  sessionYear: number | null
}

/** Toggle `item` in `set`, returning a new Set (never mutates the input) —
 * the shared primitive behind subject multi-select and per-subject paper
 * multi-select. */
export function toggleInSet<T>(set: ReadonlySet<T>, item: T): Set<T> {
  const next = new Set(set)
  if (next.has(item)) next.delete(item)
  else next.add(item)
  return next
}

/** Build the `PUT /api/me/student-profile/enrolments` body from S-01 drafts.
 * `targetGrade`/`sessionMonth`/`sessionYear` pass through as `null` when the
 * student skipped them — S-01's target-grade/session fields are per-subject
 * and skippable, same D4.5 rule as every S-02 field. */
export function buildEnrolmentPayload(drafts: SubjectDraft[]): EnrolmentUpsert[] {
  return drafts.map((draft) => ({
    subjectCode: draft.subjectCode,
    targetGrade: draft.targetGrade,
    sessionMonth: draft.sessionMonth,
    sessionYear: draft.sessionYear,
    papers: [...draft.papers].sort((a, b) => a - b),
  }))
}

// ── S-02 questionnaire ───────────────────────────────────────────────────

/** Scalar S-02 answers. `undefined` = not yet answered/skipped (never sent);
 * a present key (including an explicit `null`, e.g. "no external lessons"
 * mapping to `false`, which is a real answer, not a skip) is sent as-is. */
export interface QuestionnaireAnswers {
  schoolName?: string | null
  hasExternalLessons?: boolean | null
  weeklyStudyHours?: number | null
  gradeLevel?: string | null
  qualificationLevel?: string | null
}

/** Build the `PATCH /api/me/student-profile` body: only keys the student
 * actually touched are present. This is the D4.5 enforcement point for the
 * scalar questions — a skipped field is dropped here, never sent as `0`,
 * `false`, or any other sentinel, and `JSON.stringify` then drops the
 * `undefined` key entirely rather than serialising it. */
export function buildProfilePatchPayload(
  answers: QuestionnaireAnswers,
): Record<string, string | boolean | number | null> {
  const out: Record<string, string | boolean | number | null> = {}
  for (const [key, value] of Object.entries(answers)) {
    if (value !== undefined) out[key] = value
  }
  return out
}

/** Build one subject's `PUT .../confidence-ratings` body. A topic absent
 * from `ratings` (never rated, or explicitly `undefined`) is dropped —
 * mirrors the full-replace-but-only-what-was-touched semantics the backend
 * expects (an omitted topic has no rating stored, not a rating of 0). */
export function buildConfidenceRatingsPayload(
  ratings: Partial<Record<string, number>>,
): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [topic, rating] of Object.entries(ratings)) {
    if (rating !== undefined) out[topic] = rating
  }
  return out
}

// ── S-02 one-question-per-view step sequence ────────────────────────────

export type QuestionnaireStepKind =
  | "school"
  | "externalLessons"
  | "weeklyHours"
  | "gradeLevel"
  | "confidence"

export interface QuestionnaireStepDef {
  id: string
  kind: QuestionnaireStepKind
  /** Only set for `kind === "confidence"` — one step per enrolled subject. */
  subjectCode?: string
}

/**
 * The ordered S-02 question sequence: 4 fixed scalar questions, then one
 * confidence step per subject the student selected in S-01 (in S-01's
 * selection order). Every step is independently skippable — this only
 * decides *order*, not which are required.
 *
 * Target grade is deliberately NOT re-asked here even though the UI spec's
 * S-02 "Contains" prose lists "target grades per subject" alongside it: the
 * same spec's S-01 "Interactions" line is unambiguous that target grade is
 * captured "per subject" *at S-01 selection time* ("each selected subject
 * expands to capture papers and target grade"), and the DTO has exactly one
 * `targetGrade` per enrolment — there is no second slot for an S-02 answer
 * to write to. Asking twice would either silently overwrite S-01's answer or
 * be a dead question; both are worse than resolving the overlap once, here.
 */
export function buildQuestionnaireSteps(subjectCodes: string[]): QuestionnaireStepDef[] {
  return [
    { id: "school", kind: "school" },
    { id: "externalLessons", kind: "externalLessons" },
    { id: "weeklyHours", kind: "weeklyHours" },
    { id: "gradeLevel", kind: "gradeLevel" },
    ...subjectCodes.map((subjectCode) => ({
      id: `confidence-${subjectCode}`,
      kind: "confidence" as const,
      subjectCode,
    })),
  ]
}

/** Keep a step index inside `[0, totalSteps - 1]` (or `0` for an empty
 * sequence) — the one place "next" past the last step or "back" past the
 * first is decided, so the wizard component never renders an out-of-range
 * step. */
export function clampStepIndex(index: number, totalSteps: number): number {
  if (totalSteps <= 0) return 0
  return Math.min(Math.max(index, 0), totalSteps - 1)
}

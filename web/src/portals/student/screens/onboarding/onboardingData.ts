/*
 * Pure data + logic for the S-01/S-02 onboarding wizard. No React, no DOM —
 * this is what `web/tests/unit/onboarding.test.ts` exercises directly
 * (`vitest.config.ts` runs the unit suite in a Node environment with no
 * jsdom/@testing-library, D3.20 — component behaviour is Playwright's job,
 * not this file's; this file is the pure logic a browser test can't
 * cheaply pin, especially the D4.5 skip-produces-no-value rule).
 *
 * Curriculum data (subject names, paper numbers/names, syllabus topic
 * labels, qualification levels, session months, target grades) used to be
 * mirrored here from the same backend sources it now fetches directly:
 * `GET /api/reference` (`web/src/lib/referenceTypes.ts`,
 * `web/src/lib/reference.ts`). This module holds only the wizard logic that
 * has no backend equivalent — building payloads, sequencing S-02's
 * one-question-per-view steps, and picking the S-03 placement-invite
 * target from the fetched catalogue.
 */

import type { CatalogueSubject } from "@/lib/referenceTypes"
import type { EnrolmentUpsert } from "@/lib/meTypes"

export const WEEKLY_HOURS_MIN = 0
/** UI-only cap, tighter than the backend's 0..80 validation ceiling — 40
 * covers every realistic weekly-study answer; a student's own text isn't
 * lost by capping the slider (the backend bound still applies server-side). */
export const WEEKLY_HOURS_MAX = 40

export const CONFIDENCE_MIN = 1
export const CONFIDENCE_MAX = 5

/**
 * Which subject's placement invite (S-03) to send the student to when they
 * finish S-02, or `null` if they enrolled in none — in which case there is no
 * placement test to invite them into and the caller sends them to S-06.
 *
 * Deliberately NOT `Object.keys(drafts)[0]`. The drafts object is keyed by
 * syllabus code, and JS enumerates integer-like string keys first, ahead of
 * every other key's insertion order. All of today's codes have a leading zero
 * and so are not integer-like — insertion order happens to survive, which is
 * exactly what makes the bug invisible now and live the day a code without a
 * leading zero is added. Ordering by the catalogue instead means the student
 * is sent to the first subject *as presented to them in S-01*, which stays
 * true whatever the codes look like.
 *
 * `subjects` is the fetched catalogue rather than a module constant, so an
 * empty array (query still loading) correctly yields `null` instead of
 * silently claiming the student enrolled in nothing.
 */
export function placementInviteSubject(
  enrolledCodes: readonly string[],
  subjects: readonly CatalogueSubject[],
): string | null {
  const enrolled = new Set(enrolledCodes)
  return subjects.find((subject) => enrolled.has(subject.code))?.code ?? null
}

// ── S-01 subject/paper/target selection ─────────────────────────────────

export interface SubjectDraft {
  subjectCode: string
  qualificationLevel: string | null
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
    qualificationLevel: draft.qualificationLevel,
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

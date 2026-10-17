/*
 * Pure selectors over `ReferenceData`. No React, no fetching — this is what
 * `web/tests/unit/reference.test.ts` exercises directly, the same split
 * `onboardingData.ts` uses (the unit suite runs in Node with no jsdom, so
 * component behaviour belongs to Playwright and pure logic belongs here).
 *
 * Every selector accepts `undefined` for the reference payload, because that
 * is what react-query hands a component on its first render. Degrading to the
 * raw syllabus code is deliberate: it is the exact fallback the seven lookup
 * screens had before the catalogue was fetched, so nothing regresses while the
 * query is in flight.
 */

import type { CatalogueSubject, ReferenceData, TargetGradeVocabulary } from "@/lib/referenceTypes"

/**
 * How many of a subject's top-level topics S-02's confidence step asks about.
 *
 * The endpoint returns every top-level topic — 0606 has fourteen — because how
 * many to ask is a UI decision and which ones exist is a curriculum fact. Three
 * is what S-01/S-02 shipped with; changing it should be a deliberate edit with
 * a test failure attached, which is why the unit suite pins the number.
 */
export const CONFIDENCE_TOPICS_SHOWN = 3

/** The catalogue entry for a code, or null when unknown or still loading. */
export function subjectFor(
  reference: ReferenceData | undefined,
  code: string,
): CatalogueSubject | null {
  return reference?.subjects.find((s) => s.code === code) ?? null
}

/** A subject's display name, falling back to the raw code. */
export function subjectNameFor(reference: ReferenceData | undefined, code: string): string {
  return subjectFor(reference, code)?.name ?? code
}

/** The topics S-02 asks a confidence rating for. */
export function confidenceTopicsFor(subject: CatalogueSubject | null): string[] {
  return (subject?.topics ?? []).slice(0, CONFIDENCE_TOPICS_SHOWN)
}

/**
 * The grades a student may set as a target for one subject.
 *
 * Keyed on the subject and the tier of the papers they ticked, because the
 * vocabularies genuinely differ that way: 0580 Core publishes C–G with no A*,
 * 0580 Extended publishes A*–E with no F/G, and 0625 publishes A*–G. Returns
 * an empty list when no vocabulary matches, so the picker renders nothing
 * rather than an invented grade set.
 */
export function targetGradesFor(
  reference: ReferenceData | undefined,
  subjectCode: string,
  tier: string | null,
): string[] {
  if (!reference) return []
  const forSubject = reference.targetGradeVocabularies.filter(
    (v: TargetGradeVocabulary) => v.subjectCode === subjectCode,
  )
  // An exact tier match first; then the untiered vocabulary, which is what an
  // untiered subject (0606) publishes and what a student who has ticked no
  // papers yet should see.
  return (
    forSubject.find((v) => v.tier === tier)?.grades ??
    forSubject.find((v) => v.tier === null)?.grades ??
    []
  )
}

/**
 * The tier implied by the papers a student ticked for one subject.
 *
 * Extended wins when both are present: a candidate sitting any Extended paper
 * is an Extended candidate, and offering them the Core vocabulary would cap
 * their target at C. Returns null when nothing is ticked or the subject is
 * untiered, which `targetGradesFor` treats as "use the untiered vocabulary".
 */
export function tierForPapers(subject: CatalogueSubject | null, papers: readonly number[]): string | null {
  if (!subject) return null
  const tiers = new Set(
    papers
      .map((n) => subject.papers.find((p) => p.number === n)?.tier)
      .filter((t): t is string => Boolean(t)),
  )
  if (tiers.has("extended")) return "extended"
  if (tiers.has("core")) return "core"
  return null
}

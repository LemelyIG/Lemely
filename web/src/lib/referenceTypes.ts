/*
 * TS interfaces mirroring `lemely/web/schemas_reference.py` field-for-field
 * (camelCase). `GET /api/reference` is reachable by every authenticated role.
 *
 * This module replaces every hardcoded backend-owned table the frontend used
 * to declare: the subject catalogue, the grade vocabularies, qualification
 * levels, session months and difficulty bands. Adding a constant here that
 * mirrors backend truth defeats the point — fetch it.
 */

/** One paper a student can tick in S-01 (mirrors `SubjectPaperDTO`). */
export interface CataloguePaper {
  number: number
  name: string
  /** `"core"`, `"extended"`, or null for an untiered subject such as 0606. */
  tier: string | null
  practical: boolean
}

/** One offered subject (mirrors `SubjectCatalogueDTO`).
 *
 * `qualificationLevel` is the subject's own, not a student preference: 0580,
 * 0606 and 0625 are all IGCSE syllabuses, so S-01 displays it instead of
 * asking. `topics` are `"<code> <name>"` strings in syllabus order — the
 * vocabulary `ConfidenceRating.topic` speaks. Never compose that string here.
 */
export interface CatalogueSubject {
  code: string
  name: string
  board: string
  qualificationLevel: string | null
  papers: CataloguePaper[]
  topics: string[]
}

/** The grades a student may aim for in one subject at one tier.
 *
 * Keyed by subject, not only by qualification level: 0580 Extended publishes
 * A*-E while 0625 Extended publishes A*-G, so a coarser key would offer a
 * 0580 student an F they cannot be awarded.
 */
export interface TargetGradeVocabulary {
  subjectCode: string
  qualificationLevel: string | null
  tier: string | null
  grades: string[]
}

/** A `(value, label)` pair for an enumeration the UI renders. */
export interface LabelledValue {
  value: string
  label: string
}

/** Response for `GET /api/reference` (mirrors `ReferenceDTO`). */
export interface ReferenceData {
  subjects: CatalogueSubject[]
  targetGradeVocabularies: TargetGradeVocabulary[]
  qualificationLevels: LabelledValue[]
  sessionMonths: LabelledValue[]
  difficultyBands: string[]
}

/**
 * The four CAIE qualification levels a subject enrolment can carry (mirrors
 * `lemely.db.models.enums.QualificationLevel`). Single source of truth for
 * this label table — `subjectIdentifier` (`@/lib/subjectIdentifier`) and
 * onboarding's `SubjectsStep` both import it rather than keeping their own
 * copy.
 */
export const QUALIFICATION_LEVELS: { value: string; label: string }[] = [
  { value: "igcse", label: "IGCSE" },
  { value: "o_level", label: "O-Level" },
  { value: "as_level", label: "AS-Level" },
  { value: "a_level", label: "A-Level" },
]

/** The human label for a raw qualification-level value, or `null` for
 * null/undefined/unrecognised — never an invented label. */
export function qualificationLevelLabel(value: string | null | undefined): string | null {
  if (!value) return null
  return QUALIFICATION_LEVELS.find((l) => l.value === value)?.label ?? null
}

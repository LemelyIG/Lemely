import type { LabelledValue } from "@/lib/referenceTypes"

/**
 * The human label for a raw qualification-level value, or `null` for
 * null/undefined/unrecognised — never an invented label.
 *
 * The table itself is served by `/api/reference` (it mirrors
 * `lemely.db.models.enums.QualificationLevel`); this module keeps only the
 * lookup, so there is no second copy of the values in the frontend.
 */
export function qualificationLevelLabel(
  levels: LabelledValue[] | undefined,
  value: string | null | undefined,
): string | null {
  if (!value) return null
  return levels?.find((l) => l.value === value)?.label ?? null
}

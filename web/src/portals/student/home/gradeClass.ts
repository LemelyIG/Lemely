/* Shared class strings for the Home screen: press feedback, focus ring, hit area, grade colour. */

const GRADE_TEXT: Record<string, string> = {
  "A*": "text-grade-a-star",
  A: "text-grade-a",
  B: "text-grade-b",
  C: "text-grade-c",
  D: "text-grade-d",
  E: "text-grade-e",
  F: "text-grade-f",
  G: "text-grade-g",
  U: "text-grade-u",
}

/** Text colour for a grade letter; unknown letters stay neutral. */
export function gradeText(grade: string): string {
  return GRADE_TEXT[grade.trim().toUpperCase()] ?? "text-on-surface"
}

export const PRESS =
  "motion-safe:transition-transform motion-safe:duration-150 motion-safe:ease-out motion-safe:active:scale-[0.97]"
export const ROW_PRESS =
  "motion-safe:transition-transform motion-safe:duration-150 motion-safe:ease-out motion-safe:active:scale-[0.985]"
export const FOCUS =
  "outline-none focus-visible:outline-solid focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"
/** Grows the tap area to 44px tall without changing the visible shape. */
export const HIT = "relative after:absolute after:inset-x-0 after:-inset-y-1.5 after:content-['']"

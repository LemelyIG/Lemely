/** Maps a CAIE letter grade to its Jewel scale token (DESIGN.md "Grade scale"). */
export type GradeTone = "a-star" | "a" | "b" | "c" | "d" | "e" | "u"

const TONES: Record<string, GradeTone> = { "A*": "a-star", A: "a", B: "b", C: "c", D: "d", E: "e", U: "u" }

export function gradeTone(grade: string): GradeTone | null {
  return TONES[grade.trim().toUpperCase()] ?? null
}

/**
 * `large`: the letter renders at WCAG large-text size (>= 18.66px bold, i.e.
 * the title rung or above). `small`: anything below that.
 */
export type GradeChipSize = "small" | "large"

/*
 * Literal tables: Tailwind only emits classes it sees spelled out.
 * White letters clear 3:1 on every Jewel fill (large-text AA) but not 4.5:1,
 * so white-on-fill is only allowed for a `large` letter.
 */
const FILL: Record<GradeTone, string> = {
  "a-star": "bg-grade-a-star",
  a: "bg-grade-a",
  b: "bg-grade-b",
  c: "bg-grade-c",
  d: "bg-grade-d",
  e: "bg-grade-e",
  u: "bg-grade-u",
}
const BORDER: Record<GradeTone, string> = {
  "a-star": "border-grade-a-star",
  a: "border-grade-a",
  b: "border-grade-b",
  c: "border-grade-c",
  d: "border-grade-d",
  e: "border-grade-e",
  u: "border-grade-u",
}

/**
 * Tailwind classes for a grade chip, always labelled.
 *
 * - `large` (letter >= 18.66px bold): Jewel fill, white letter.
 * - `small` (the default, letter below large-text size): outlined, a 2px Jewel
 *   border on `surface-container-lowest` with an `on-surface` letter, because
 *   a small white letter on a Jewel fill fails AA.
 *
 * The small variant includes `border-2`, so callers must not add their own
 * border width. An unknown grade gets a neutral chip at either size.
 */
export function gradeChipClass(grade: string, { size = "small" }: { size?: GradeChipSize } = {}): string {
  const tone = gradeTone(grade)
  if (size === "large") {
    return tone ? `${FILL[tone]} text-white` : "bg-surface-container-high text-on-surface"
  }
  return tone
    ? `border-2 ${BORDER[tone]} bg-surface-container-lowest text-on-surface`
    : "border-2 border-outline bg-surface-container-lowest text-on-surface"
}

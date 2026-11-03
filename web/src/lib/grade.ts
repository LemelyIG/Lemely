/** Maps a CAIE letter grade to its Jewel scale token (DESIGN.md "Grade scale"). */
export type GradeTone = "a-star" | "a" | "b" | "c" | "d" | "e" | "u"

const TONES: Record<string, GradeTone> = { "A*": "a-star", A: "a", B: "b", C: "c", D: "d", E: "e", U: "u" }

export function gradeTone(grade: string): GradeTone | null {
  return TONES[grade.trim().toUpperCase()] ?? null
}

/** Tailwind classes for a grade chip: Jewel fill, white letter, always labelled. */
export function gradeChipClass(grade: string): string {
  const tone = gradeTone(grade)
  return tone ? `bg-grade-${tone} text-white` : "bg-surface-container-high text-on-surface"
}

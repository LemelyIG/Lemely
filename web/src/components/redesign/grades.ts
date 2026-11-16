/** 'A*' | 'A' | … | 'G' | 'U' */
export type Grade = string

const GRADE_VARS: Record<string, string> = {
  "A*": "--grade-a-star",
  A: "--grade-a",
  B: "--grade-b",
  C: "--grade-c",
  D: "--grade-d",
  E: "--grade-e",
  F: "--grade-f",
  G: "--grade-g",
  U: "--grade-u",
}

export function gradeColorVar(grade: Grade): string {
  return `var(${GRADE_VARS[grade.trim().toUpperCase()] ?? "--md-outline"})`
}

/** Ghost heights for an empty path (sjf.js ghostPath). */
export const EMPTY_GHOST_HEIGHTS = [30, 45, 52, 70] as const

/** Bars run from 40% of the marks up to the goal line, so each grade reads as a real step (sjf.js hOf). */
export function stepHeight(pct: number, goalPct = 100): number {
  if (!Number.isFinite(pct)) return 0
  const floor = 40
  if (goalPct <= floor) return 100
  return Math.max(0, Math.min(100, Math.round(((pct - floor) / (goalPct - floor)) * 100)))
}

export interface PaperScore {
  pct: number
  caption?: string
  marks?: { got: number; max: number }
}

/** The Mono line under a bar: the caption, else got/max, else nothing. */
export function paperCaption(p: PaperScore): string | undefined {
  return p.caption ?? (p.marks ? `${p.marks.got}/${p.marks.max}` : undefined)
}

/** How a bar's score is spoken: marks in words when known, else the caption, else the percentage. */
export function paperSpoken(p: PaperScore): string {
  if (p.marks) return `${p.marks.got} out of ${p.marks.max}`
  return p.caption ?? `${p.pct}%`
}

export function stepsSummary(
  papers: readonly (PaperScore & { label: string; grade: Grade })[],
  goal?: Grade,
  goalNote?: string,
): string {
  const parts = papers.map((p) => `${p.grade}, ${paperSpoken(p)} in ${p.label}`)
  let text = parts.length ? `Marks so far: ${parts.join("; ")}.` : "No papers yet."
  if (goal) text += ` Goal ${goal}${goalNote ? `, ${goalNote}` : ""}.`
  return text
}

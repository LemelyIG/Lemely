/*
 * C-18 · pure layout and copy for the higher / same / lower figure (SPEC §d,
 * decision-log rows 8 and 15e).
 *
 * The figure's title is fixed. "Change in grade while with this tutor" is the
 * wording the user locked in row 8b: it says what was measured (a change that
 * happened while a student had this tutor) and stops short of saying who caused
 * it. A caller cannot pass another title; the component imports this constant.
 *
 * All three parts are always listed, an empty one as 0 with no width, for the
 * reason `ordinalLayout.ts` lists zero rungs: "no one went down" is a finding,
 * and a missing part is not.
 */

export const GRADE_CHANGE_TITLE = "Change in grade while with this tutor"

export type GradeChangeKey = "lower" | "same" | "higher"

/** Left to right, as the SPEC lists them: "Lower grade · Same grade · Higher grade". */
export const GRADE_CHANGE_PARTS: readonly { key: GradeChangeKey; label: string }[] = [
  { key: "lower", label: "Lower grade" },
  { key: "same", label: "Same grade" },
  { key: "higher", label: "Higher grade" },
]

export interface GradeChangePart {
  key: GradeChangeKey
  label: string
  count: number
  startPct: number
  widthPct: number
}

export interface GradeChangeLayout {
  /** Students across the three parts. */
  n: number
  parts: GradeChangePart[]
}

export function layoutGradeChange(change: {
  lower: number | null
  same: number | null
  higher: number | null
}): GradeChangeLayout {
  const counts = GRADE_CHANGE_PARTS.map((part) => Math.max(0, change[part.key] ?? 0))
  const n = counts.reduce((sum, count) => sum + count, 0)
  let start = 0
  const parts = GRADE_CHANGE_PARTS.map((part, i) => {
    const widthPct = n === 0 ? 0 : (counts[i] / n) * 100
    const laid: GradeChangePart = {
      key: part.key,
      label: part.label,
      count: counts[i],
      startPct: start,
      widthPct,
    }
    start += widthPct
    return laid
  })
  return { n, parts }
}

function students(n: number): string {
  return `${n} ${n === 1 ? "student" : "students"}`
}

/** The chart's accessible name: one full sentence naming the title, n and each part. */
export function gradeChangeAriaLabel(layout: GradeChangeLayout): string {
  const parts = layout.parts.map((part) => `${part.label.toLowerCase()} ${part.count}`).join(", ")
  return `${GRADE_CHANGE_TITLE}, ${students(layout.n)}: ${parts}.`
}

/** The `n` caption under the figure. */
export function gradeChangeCaption(n: number): string {
  return `n = ${students(n)} with a grade to compare.`
}

/** Rows for the table alternative: part, then the count as text. */
export function gradeChangeTableRows(layout: GradeChangeLayout): string[][] {
  return layout.parts.map((part) => [part.label, String(part.count)])
}

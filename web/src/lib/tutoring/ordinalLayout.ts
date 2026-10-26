/*
 * C-17 · pure layout for the ordered grade bar (SPEC §d, row 8, ADR-T04).
 *
 * The component draws; every decision lives here so the node-only runner can
 * test it. What this module settles:
 *
 *   - The ladder is the one `OutcomesDTO.ladder` serves, in its order. It is
 *     never declared in the frontend (`noHardcodedReferenceData.test.ts`).
 *   - Every rung is listed, a rung with no student as 0. Hiding it would turn
 *     "nobody got a U" into "we did not look", and an ordinal scale with a gap
 *     in it reads as a different scale.
 *   - A grade the ladder does not list is kept (after the ladder) rather than
 *     dropped, because dropping it would make the bar add up to fewer students
 *     than n says.
 *   - A segment too narrow to hold its label carries the label outside, below
 *     the bar, spread apart so neighbouring labels never overprint.
 *   - Nothing here rounds a share for display: widths are exact proportions,
 *     and the text alternative speaks counts, not percentages (never invent
 *     precision).
 */

export interface OrdinalBucket {
  grade: string
  count: number
}

export interface OrdinalRung {
  grade: string
  count: number
}

export interface OrdinalSegment {
  grade: string
  count: number
  /** Left edge and width as a percentage of the bar. */
  startPct: number
  widthPct: number
  centrePct: number
  labelPlacement: "inside" | "outside"
  /** Where the label sits along the bar. Equals the centre when inside. */
  labelPct: number
}

export interface OrdinalLayout {
  /** Students counted across every rung. */
  n: number
  /** Every rung in ladder order, zero rungs included. */
  rungs: OrdinalRung[]
  /** One per non-zero rung, in ladder order. */
  segments: OrdinalSegment[]
}

/*
 * Sized for a label like "A* 12" in the 12px data face on the narrowest phone,
 * where the bar is about 290px wide: that label is about 36px, or 12.5%.
 */
/** A segment narrower than this share of the bar cannot hold its label. */
export const MIN_INSIDE_LABEL_PCT = 12
/** Closest two outside labels may sit, as a share of the bar. */
export const MIN_OUTSIDE_LABEL_GAP_PCT = 12
/** Keep an outside label this far from either end so it is not clipped. */
export const LABEL_EDGE_PCT = 6

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value))
}

/**
 * Move centres apart until each is at least `minGap` from the one before,
 * keeping them in `[lo, hi]` and in order. Input is ascending. A forward pass
 * pushes right; a backward pass pulls back whatever the forward pass pushed
 * past `hi`. When the labels cannot all fit (more than the range allows) the
 * result is the tightest packing from `lo`, never an overlap-free lie.
 */
export function spreadLabelPositions(
  centres: readonly number[],
  minGap: number,
  lo = 0,
  hi = 100,
): number[] {
  const out = centres.map((c) => clamp(c, lo, hi))
  for (let i = 1; i < out.length; i++) out[i] = Math.max(out[i], out[i - 1] + minGap)
  for (let i = out.length - 1; i >= 0; i--) {
    const ceiling = i === out.length - 1 ? hi : out[i + 1] - minGap
    out[i] = Math.min(out[i], ceiling)
  }
  return out
}

export function layoutOrdinal(
  ladder: readonly string[],
  buckets: readonly OrdinalBucket[],
): OrdinalLayout {
  const counts = new Map<string, number>()
  for (const bucket of buckets) {
    counts.set(bucket.grade, (counts.get(bucket.grade) ?? 0) + Math.max(0, bucket.count))
  }

  const order = [...new Set(ladder)]
  for (const grade of counts.keys()) if (!order.includes(grade)) order.push(grade)

  const rungs: OrdinalRung[] = order.map((grade) => ({ grade, count: counts.get(grade) ?? 0 }))
  const n = rungs.reduce((sum, rung) => sum + rung.count, 0)

  const segments: OrdinalSegment[] = []
  let start = 0
  for (const rung of rungs) {
    if (rung.count === 0) continue
    const widthPct = (rung.count / n) * 100
    const centrePct = start + widthPct / 2
    segments.push({
      grade: rung.grade,
      count: rung.count,
      startPct: start,
      widthPct,
      centrePct,
      labelPlacement: widthPct >= MIN_INSIDE_LABEL_PCT ? "inside" : "outside",
      labelPct: centrePct,
    })
    start += widthPct
  }

  const outside = segments.filter((s) => s.labelPlacement === "outside")
  const spread = spreadLabelPositions(
    outside.map((s) => s.centrePct),
    MIN_OUTSIDE_LABEL_GAP_PCT,
    LABEL_EDGE_PCT,
    100 - LABEL_EDGE_PCT,
  )
  outside.forEach((segment, i) => {
    segment.labelPct = spread[i]
  })

  return { n, rungs, segments }
}

function students(n: number): string {
  return `${n} ${n === 1 ? "student" : "students"}`
}

/** The chart's accessible name: one full sentence, every rung spoken. */
export function distributionAriaLabel(subjectName: string | undefined, layout: OrdinalLayout): string {
  const lead = subjectName ? `${subjectName}: grades of` : "Grades of"
  const rungs = layout.rungs.map((rung) => `${rung.grade} ${rung.count}`).join(", ")
  return `${lead} ${students(layout.n)}. ${rungs}.`
}

/** The `n` caption under the figure. */
export function distributionCaption(nGraded: number, nWithoutGrade: number | null): string {
  const base = `n = ${students(nGraded)} with a grade.`
  if (nWithoutGrade === null || nWithoutGrade <= 0) return base
  const more = `${nWithoutGrade} more ${nWithoutGrade === 1 ? "has" : "have"} no grade to show.`
  return `${base} ${more}`
}

/** Rows for the table alternative: grade, then the count as text. */
export function distributionTableRows(layout: OrdinalLayout): string[][] {
  return layout.rungs.map((rung) => [rung.grade, String(rung.count)])
}

/** The first sentence of S-34's insufficient-results copy. */
export const INSUFFICIENT_RESULTS_HEADING = "Results are hidden for now"

/** The rest of it. `k` comes from the figure, so the number is never a literal here. */
export function insufficientResultsBody(k: number): string {
  return `We show them only when at least ${k} ${k === 1 ? "student has" : "students have"} a marked paper from their time with this tutor, and only when no one's grade could be worked out from them.`
}

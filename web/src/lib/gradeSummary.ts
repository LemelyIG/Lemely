import { gradeBand } from "@/components/ui/grade-badge"

/**
 * Task 9 (C3d) · The `GradeDistributionPanel` headline count.
 *
 * Sums the `count` of every bucket whose `gradeBand(grade) === "top"` —
 * `gradeBand` itself (`components/ui/grade-badge.tsx`) groups A*, A and B
 * into "top", so this is genuinely "students on A*, A or B", not literally just
 * "A* or A" (the ledger's/DESIGN's own shorthand for "the top band").
 * Reuses the exact same band function the bar chart already colors its bars
 * with (`GRADE_BAND_TOKEN[gradeBand(...)]` in `ClassAnalytics.tsx`), so the
 * headline number and "which bars are the top-band color" can never
 * disagree about where the line sits.
 */
export function topGradeCount(buckets: readonly { grade: string; count: number }[]): number {
  return buckets.reduce((sum, b) => (gradeBand(b.grade) === "top" ? sum + b.count : sum), 0)
}

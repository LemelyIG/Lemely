import type { AtRiskStudent, ClassSummary, Overview } from "@/lib/teacherTypes"

export const REVIEW_THRESHOLD_BAND = 7

export interface ReviewQueueModel {
  count: number
  bars: { band: number; height: number; low: boolean }[]
  estimate: string | null
  empty: boolean
}

export function reviewQueueModel(
  o: Pick<Overview, "pendingReviewCount" | "reviewConfidenceBuckets" | "reviewEstimateMinutes">,
): ReviewQueueModel {
  const counts = Array.from({ length: 10 }, (_, i) => o.reviewConfidenceBuckets?.[i] ?? 0)
  const max = Math.max(0, ...counts)
  return {
    count: o.pendingReviewCount,
    bars: counts.map((c, band) => ({ band, height: max ? c / max : 0, low: band < REVIEW_THRESHOLD_BAND })),
    estimate: o.pendingReviewCount > 0 && o.reviewEstimateMinutes > 0 ? `about ${o.reviewEstimateMinutes} min` : null,
    empty: o.pendingReviewCount === 0,
  }
}

export interface AtRiskRowModel {
  initials: string
  name: string
  reason: string
  from: string | null
  to: string | null
}

export function atRiskRowModel(s: AtRiskStudent): AtRiskRowModel {
  const initials = s.name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("")
  return {
    initials,
    name: s.name,
    reason: s.flags[0]?.summary ?? "",
    from: s.grade ? (s.previousGrade ?? null) : null,
    to: s.grade || null,
  }
}

export interface ClassCardModel {
  id: string
  title: string
  meta: string
  average: string | null
  weakTopic: string | null
}

export function classCardModel(c: ClassSummary): ClassCardModel {
  const students = `${c.studentCount} ${c.studentCount === 1 ? "student" : "students"}`
  return {
    id: c.id,
    title: c.label,
    meta: c.subjectCode ? `${c.subjectCode} · ${students}` : students,
    average: c.average === null ? null : `${Math.round(c.average)}%`,
    weakTopic: c.topWeakness,
  }
}

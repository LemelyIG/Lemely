import type { AtRiskStudent, ClassSummary, Overview } from "@/lib/teacherTypes"

/** Used only when an older server omits `reviewConfidenceThreshold`; mirrors REVIEW_CONFIDENCE_THRESHOLD. */
export const FALLBACK_REVIEW_THRESHOLD = 0.9

export interface ReviewQueueModel {
  /** Every open review-queue item (one per flagged question per reason). */
  count: number
  bars: { band: number; height: number; low: boolean }[]
  /** Items in the confidence bands wholly below the threshold. */
  lowCount: number
  /** The server's review threshold as a whole percentage. */
  thresholdPct: number
  estimate: string | null
  empty: boolean
}

export function reviewQueueModel(
  o: Pick<Overview, "pendingReviewCount" | "reviewConfidenceBuckets" | "reviewEstimateMinutes"> &
    Partial<Pick<Overview, "reviewConfidenceThreshold">>,
): ReviewQueueModel {
  const raw = o.reviewConfidenceThreshold
  const threshold = typeof raw === "number" && Number.isFinite(raw) && raw >= 0 && raw <= 1 ? raw : FALLBACK_REVIEW_THRESHOLD
  // Band b covers [b/10, (b+1)/10); it is low when it lies wholly below the threshold.
  const thresholdBand = Math.floor(threshold * 10 + 1e-9)
  const counts = Array.from({ length: 10 }, (_, i) => o.reviewConfidenceBuckets?.[i] ?? 0)
  const max = Math.max(0, ...counts)
  return {
    count: o.pendingReviewCount,
    bars: counts.map((c, band) => ({ band, height: max ? c / max : 0, low: band < thresholdBand })),
    lowCount: counts.slice(0, thresholdBand).reduce((a, n) => a + n, 0),
    thresholdPct: Math.round(threshold * 100),
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
  /** The shown flag has been acknowledged by a teacher. */
  acknowledged: boolean
  /** Further flags beyond the one shown. */
  moreReasons: number
}

export function atRiskRowModel(s: AtRiskStudent): AtRiskRowModel {
  const initials = s.name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("")
  // An unacknowledged flag still needs a teacher, so it leads over acknowledged ones.
  const shown = s.flags.find((f) => f.acknowledged === null) ?? s.flags[0]
  return {
    initials,
    name: s.name,
    reason: shown?.summary ?? "",
    acknowledged: !!shown && shown.acknowledged !== null,
    moreReasons: Math.max(0, s.flags.length - 1),
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

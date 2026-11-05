import type { AtRiskStudent, ClassSummary, Overview } from "@/lib/teacherTypes"
import { relativeTime } from "@/lib/utils"

/** Used only when an older server omits `reviewConfidenceThreshold`; mirrors REVIEW_CONFIDENCE_THRESHOLD. */
export const FALLBACK_REVIEW_THRESHOLD = 0.9

export interface ReviewQueueModel {
  /** Every open review-queue item (one per flagged question per reason). */
  count: number
  bars: { band: number; height: number; low: boolean }[]
  /** Items in the confidence bands wholly below the threshold. */
  lowCount: number
  /** Every open item scored below the threshold, so "answers below N%" is literally true. */
  allLow: boolean
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
  const lowCount = counts.slice(0, thresholdBand).reduce((a, n) => a + n, 0)
  return {
    count: o.pendingReviewCount,
    bars: counts.map((c, band) => ({ band, height: max ? c / max : 0, low: band < thresholdBand })),
    lowCount,
    allLow: o.pendingReviewCount > 0 && lowCount === o.pendingReviewCount,
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

export interface ClassCardTrend {
  /** Signed percentage-point change, one decimal ("+0.4", "-1.2", "0.0"). */
  text: string
  tone: "up" | "down" | "flat"
}

export interface ClassCardModel {
  id: string
  title: string
  meta: string
  average: string | null
  weakTopic: string | null
  /** Median latest paper grade. */
  grade: string | null
  trend: ClassCardTrend | null
  /** Last paper and when the class was last active, e.g. "P4 · 3d ago". */
  meta2: string | null
  /** The weak topic's accuracy as a whole percentage. */
  weakPct: string | null
  /** The same accuracy, 0-1, for the bar. */
  weakBar: number | null
}

function trendOf(delta: number | null | undefined): ClassCardTrend | null {
  if (typeof delta !== "number" || !Number.isFinite(delta)) return null
  const text = delta.toFixed(1)
  if (text === "0.0" || text === "-0.0") return { text: "0.0", tone: "flat" }
  return delta > 0 ? { text: `+${text}`, tone: "up" } : { text, tone: "down" }
}

export function classCardModel(c: ClassSummary): ClassCardModel {
  const students = `${c.studentCount} ${c.studentCount === 1 ? "student" : "students"}`
  const accuracy = c.topWeakness && typeof c.topWeaknessAccuracy === "number" && Number.isFinite(c.topWeaknessAccuracy)
    ? Math.min(1, Math.max(0, c.topWeaknessAccuracy))
    : null
  const meta2 = [c.lastPaper, c.lastActivityAt ? relativeTime(c.lastActivityAt) : null].filter(Boolean).join(" · ")
  return {
    id: c.id,
    title: c.label,
    meta: c.subjectCode ? `${c.subjectCode} · ${students}` : students,
    average: c.average === null ? null : `${Math.round(c.average)}%`,
    weakTopic: c.topWeakness,
    grade: c.grade || null,
    trend: trendOf(c.delta),
    meta2: meta2 || null,
    weakPct: accuracy === null ? null : `${Math.round(accuracy * 100)}%`,
    weakBar: accuracy,
  }
}

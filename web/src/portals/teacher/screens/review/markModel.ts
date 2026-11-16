import { groupPoints } from "@/lib/selfReview"
import type { ResolveReviewRequest, ReviewBreakdown, ReviewItemPoint } from "@/lib/teacherTypes"

/** One scheme point as the tick list shows it. `code` is "M1", "A1", "B1"... */
export interface MarkPoint {
  markPointId: string
  code: string
  text: string
  tariff: number
  groupKey: string | null
  groupMaxMarks: number | null
  awarded: boolean
  verdictLabel: string | null
  note: string | null
  ecf: boolean
}

const CODED_TYPES = new Set(["M", "A", "B", "C", "SC"])
const VERDICT_LABEL: Record<string, string> = { withheld: "Judged absent", unverifiable: "Couldn't confirm" }

export function markPointsFrom(points: readonly ReviewItemPoint[]): MarkPoint[] {
  return [...points]
    .sort((a, b) => a.ordinal - b.ordinal)
    .map((p) => ({
      markPointId: p.markPointId,
      code: p.markType && CODED_TYPES.has(p.markType) ? `${p.markType}${p.tariff}` : p.markPointId,
      text: p.pointText,
      tariff: p.tariff,
      groupKey: p.groupKey,
      groupMaxMarks: p.groupMaxMarks,
      awarded: p.awarded,
      verdictLabel: p.verdict ? (VERDICT_LABEL[p.verdict] ?? null) : null,
      note: p.evidenceSpan ? `“${p.evidenceSpan}”` : (p.rationale ?? null),
      ecf: p.ecfApplied,
    }))
}

/** `ticked` keeps tick order (the stepper's − removes the latest). `raw` is the
 * number used when an item has no points (console papers, quizzes). */
export interface MarkState {
  ticked: string[]
  touched: boolean
  raw: number
}

export function initialMarkState(points: readonly MarkPoint[], lemely: number | null): MarkState {
  return { ticked: points.filter((p) => p.awarded).map((p) => p.markPointId), touched: false, raw: lemely ?? 0 }
}

function computed(points: readonly MarkPoint[], ticked: readonly string[]): number {
  const on = new Set(ticked)
  return groupPoints(points).reduce((sum, g) => {
    const got = g.points.filter((p) => on.has(p.markPointId)).reduce((s, p) => s + p.tariff, 0)
    return sum + Math.min(g.maxMarks, got)
  }, 0)
}

/**
 * Untouched, the total is Lemely's own mark even when its ticks don't add up
 * to it (that disagreement is often why the answer is here). The first tick
 * or step hands the total to the ticks.
 */
export function totalOf(points: readonly MarkPoint[], s: MarkState, max: number | null, lemely: number | null): number {
  const cap = max ?? Number.POSITIVE_INFINITY
  if (points.length === 0) return Math.min(cap, Math.max(0, s.raw))
  if (!s.touched && lemely != null) return lemely
  return Math.min(cap, computed(points, s.ticked))
}

export function isBlocked(points: readonly MarkPoint[], s: MarkState, id: string, max: number | null): boolean {
  if (s.ticked.includes(id)) return false
  const point = points.find((p) => p.markPointId === id)
  if (!point) return true
  if (point.groupKey) {
    const members = points.filter((p) => p.groupKey === point.groupKey)
    const tickedMembers = members.filter((p) => s.ticked.includes(p.markPointId))
    if (point.groupKey.startsWith("alt:") && tickedMembers.length > 0) return true
    const cap = point.groupMaxMarks ?? point.tariff
    if (tickedMembers.reduce((x, p) => x + p.tariff, 0) >= cap) return true
  }
  return max != null && computed(points, s.ticked) >= max
}

export function toggleTick(points: readonly MarkPoint[], s: MarkState, id: string, max: number | null): MarkState {
  if (s.ticked.includes(id)) return { ...s, touched: true, ticked: s.ticked.filter((x) => x !== id) }
  if (isBlocked(points, s, id, max)) return s
  return { ...s, touched: true, ticked: [...s.ticked, id] }
}

export function stepUp(points: readonly MarkPoint[], s: MarkState, max: number | null): MarkState {
  if (points.length === 0) return { ...s, touched: true, raw: Math.min(max ?? Number.POSITIVE_INFINITY, s.raw + 1) }
  const next = points.find((p) => !isBlocked(points, s, p.markPointId, max) && !s.ticked.includes(p.markPointId))
  return next ? { ...s, touched: true, ticked: [...s.ticked, next.markPointId] } : s
}

export function stepDown(points: readonly MarkPoint[], s: MarkState): MarkState {
  if (points.length === 0) return { ...s, touched: true, raw: Math.max(0, s.raw - 1) }
  if (s.ticked.length === 0) return s
  return { ...s, touched: true, ticked: s.ticked.slice(0, -1) }
}

export function canStep(
  points: readonly MarkPoint[],
  s: MarkState,
  max: number | null,
  lemely: number | null,
): { down: boolean; up: boolean } {
  const total = totalOf(points, s, max, lemely)
  if (points.length === 0) return { down: total > 0, up: max == null || total < max }
  const up = (max == null || total < max) && points.some((p) => !s.ticked.includes(p.markPointId) && !isBlocked(points, s, p.markPointId, max))
  return { down: s.ticked.length > 0, up }
}

export function deltaLine(total: number, lemely: number | null): string {
  if (lemely == null || total === lemely) return "as marked by Lemely"
  const d = total - lemely
  return `${d > 0 ? "+" : "−"}${Math.abs(d)} from Lemely`
}

export function primaryActionLabel(total: number, max: number | null, lemely: number | null): string {
  const verb = lemely == null || total === lemely ? "Accept" : "Save"
  return `${verb} ${total}/${max ?? "–"}`
}

/** I14/I15: on accept-as-is the note is stored internally, never shown to the student. */
export function notePlaceholder(changed: boolean): string {
  return changed ? "Note to student (optional)" : "Note for your records (optional)"
}

export function orBefore(points: readonly MarkPoint[], index: number): boolean {
  const here = points[index]
  const prev = points[index - 1]
  return !!here?.groupKey && here.groupKey.startsWith("alt:") && prev?.groupKey === here.groupKey
}

export function poolHeader(points: readonly MarkPoint[], index: number): string | null {
  const here = points[index]
  if (!here?.groupKey || !here.groupKey.startsWith("pool:")) return null
  if (points[index - 1]?.groupKey === here.groupKey) return null
  const cap = here.groupMaxMarks ?? here.tariff
  return `Up to ${cap} ${cap === 1 ? "mark" : "marks"} from these`
}

/** The method/accuracy/other split the old adjust form asked for, read off the ticks. */
export function breakdownOf(points: readonly MarkPoint[], s: MarkState): ReviewBreakdown | undefined {
  if (points.length === 0) return undefined
  const on = points.filter((p) => s.ticked.includes(p.markPointId))
  const sum = (pred: (p: MarkPoint) => boolean) => on.filter(pred).reduce((x, p) => x + p.tariff, 0)
  const type = (p: MarkPoint) => p.code.replace(/\d+$/, "")
  return {
    methodMarks: sum((p) => type(p) === "M" || type(p) === "C"),
    accuracyMarks: sum((p) => type(p) === "A"),
    otherMarks: sum((p) => !["M", "C", "A"].includes(type(p))),
    notes: null,
  }
}

export function resolveBody(a: {
  points: readonly MarkPoint[]
  state: MarkState
  max: number | null
  lemely: number | null
  note: string
  canAdjust: boolean
}): ResolveReviewRequest {
  const note = a.note.trim() || undefined
  const total = totalOf(a.points, a.state, a.max, a.lemely)
  const body: ResolveReviewRequest = {}
  if (a.canAdjust && a.lemely != null && total !== a.lemely) {
    body.overrideMarks = total
    const breakdown = breakdownOf(a.points, a.state)
    if (breakdown) body.breakdown = breakdown
  }
  if (note) body.note = note
  return body
}

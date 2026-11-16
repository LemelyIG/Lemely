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
  /** Lemely gave a mark: until the teacher touches anything, that clamped mark is the total, even if the ticks cannot add up to it. */
  anchored?: boolean
}

const clampMark = (n: number, max: number | null): number => Math.min(max ?? Number.POSITIVE_INFINITY, Math.max(0, n))

const capOf = (max: number | null): number => max ?? Number.POSITIVE_INFINITY

/** A tick set the either/or and pool rules allow: one member of an alt group,
 * and a pool never needs more than its cap (the last added may overshoot it). */
function validSet(points: readonly MarkPoint[], ticked: readonly string[], max: number | null): boolean {
  const on = new Set(ticked)
  if (computed(points, ticked) > capOf(max)) return false
  for (const g of groupPoints(points)) {
    if (!g.key) continue
    const members = g.points.filter((p) => on.has(p.markPointId))
    if (g.kind === "alternative") {
      if (members.length > 1) return false
    } else if (members.length > 0) {
      const sum = members.reduce((x, p) => x + p.tariff, 0)
      if (sum - Math.min(...members.map((p) => p.tariff)) >= g.maxMarks) return false
    }
  }
  return true
}

/**
 * One tick change that moves the group-capped total by exactly `delta` (+1 or
 * -1): add or drop a single point, else swap one for another. Null when no
 * such change exists. The ticks are the source of truth, so every step is
 * one real mark and none is dead.
 */
function move(points: readonly MarkPoint[], ticked: readonly string[], max: number | null, delta: 1 | -1): string[] | null {
  const want = computed(points, ticked) + delta
  const off = points.filter((p) => !ticked.includes(p.markPointId))
  const tryNext = (next: string[]) => (computed(points, next) === want && validSet(points, next, max) ? next : null)
  if (delta > 0) {
    for (const a of off) {
      const hit = tryNext([...ticked, a.markPointId])
      if (hit) return hit
    }
  } else {
    for (let i = ticked.length - 1; i >= 0; i--) {
      const hit = tryNext(ticked.filter((_, j) => j !== i))
      if (hit) return hit
    }
  }
  for (let i = ticked.length - 1; i >= 0; i--) {
    for (const a of off) {
      const hit = tryNext([...ticked.filter((_, j) => j !== i), a.markPointId])
      if (hit) return hit
    }
  }
  return null
}

/**
 * Starts from Lemely's own mark, clamped to [0, max]. Its ticks are kept when
 * they agree; when they disagree with its total (often why the answer is
 * here) the ticks are nudged, latest first, until they add up to that total,
 * so the stepper and the ticks always tell one story.
 */
export function initialMarkState(points: readonly MarkPoint[], lemely: number | null, max: number | null = null): MarkState {
  const raw = clampMark(lemely ?? 0, max)
  if (points.length === 0) return { ticked: [], touched: false, raw, anchored: lemely != null }
  let ticked: string[] = []
  for (const p of points) {
    if (!p.awarded) continue
    const next = [...ticked, p.markPointId]
    if (validSet(points, next, max) && computed(points, next) > computed(points, ticked)) ticked = next
  }
  if (lemely != null) {
    for (let i = 0; i < 500; i++) {
      const diff = computed(points, ticked) - raw
      if (diff === 0) break
      const next = move(points, ticked, max, diff > 0 ? -1 : 1)
      if (!next) break
      ticked = next
    }
  }
  return { ticked, touched: false, raw, anchored: lemely != null }
}

function computed(points: readonly MarkPoint[], ticked: readonly string[]): number {
  const on = new Set(ticked)
  return groupPoints(points).reduce((sum, g) => {
    const got = g.points.filter((p) => on.has(p.markPointId)).reduce((s, p) => s + p.tariff, 0)
    return sum + Math.min(g.maxMarks, got)
  }, 0)
}

/** The ticks decide the total (or the raw number when there are no points), clamped to [0, max].
 * An untouched item keeps Lemely's clamped mark, so unreachable ticks never invent an override. */
export function totalOf(points: readonly MarkPoint[], s: MarkState, max: number | null): number {
  if (points.length === 0 || (s.anchored && !s.touched)) return clampMark(s.raw, max)
  return clampMark(computed(points, s.ticked), max)
}

/** False only when the teacher has no way to enter a mark: no points, no maximum to step within, and no mark from Lemely. */
export function canSave(points: readonly MarkPoint[], s: MarkState, max: number | null, lemely: number | null): boolean {
  return points.length > 0 || max != null || lemely != null || s.touched
}

/** Shown when Lemely's own mark is above the maximum and was clamped. */
export function clampNote(lemely: number | null, max: number | null): string | null {
  if (lemely == null || max == null || lemely <= max) return null
  return `Lemely gave ${lemely}, above the maximum of ${max}, so it is shown as ${max}`
}

export function isBlocked(points: readonly MarkPoint[], s: MarkState, id: string, max: number | null): boolean {
  if (s.ticked.includes(id)) return false
  const point = points.find((p) => p.markPointId === id)
  if (!point) return false
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
  if (!points.some((p) => p.markPointId === id) || isBlocked(points, s, id, max)) return s
  return { ...s, touched: true, ticked: [...s.ticked, id] }
}

/** One mark up. With an unknown maximum the stepper is off and this is a no-op. */
export function stepUp(points: readonly MarkPoint[], s: MarkState, max: number | null): MarkState {
  if (max == null) return s
  if (points.length === 0) return s.raw >= max ? s : { ...s, touched: true, raw: s.raw + 1 }
  const next = move(points, s.ticked, max, 1)
  return next ? { ...s, touched: true, ticked: next } : s
}

/** One mark down. With an unknown maximum the stepper is off and this is a no-op. */
export function stepDown(points: readonly MarkPoint[], s: MarkState, max: number | null): MarkState {
  if (max == null) return s
  if (points.length === 0) return s.raw <= 0 ? s : { ...s, touched: true, raw: s.raw - 1 }
  const next = move(points, s.ticked, max, -1)
  return next ? { ...s, touched: true, ticked: next } : s
}

export function canStep(
  points: readonly MarkPoint[],
  s: MarkState,
  max: number | null,
): { down: boolean; up: boolean } {
  if (max == null) return { down: false, up: false }
  if (points.length === 0) return { down: s.raw > 0, up: s.raw < max }
  return { down: move(points, s.ticked, max, -1) != null, up: move(points, s.ticked, max, 1) != null }
}

export function deltaLine(total: number, lemely: number | null): string {
  if (lemely == null) return "Lemely gave no mark"
  if (total === lemely) return "as marked by Lemely"
  const d = total - lemely
  return `${d > 0 ? "+" : "−"}${Math.abs(d)} from Lemely`
}

export function primaryActionLabel(total: number, max: number | null, lemely: number | null): string {
  const verb = lemely != null && total === lemely ? "Accept" : "Save"
  return max == null ? `${verb} ${total}` : `${verb} ${total}/${max}`
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
  const total = totalOf(a.points, a.state, a.max)
  const body: ResolveReviewRequest = {}
  if (a.canAdjust && canSave(a.points, a.state, a.max, a.lemely) && total !== a.lemely) {
    body.overrideMarks = total
    const breakdown = breakdownOf(a.points, a.state)
    if (breakdown) body.breakdown = breakdown
  }
  if (note) body.note = note
  return body
}

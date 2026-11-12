/*
 * Native frame sheets and swipe-back: release decisions, pure (D10).
 * Units: px and px/ms; positive dy is downward, positive dx is away from the
 * leading edge (callers multiply by the RTL sign first).
 */
export type Detent = "content" | "medium" | "large"

export const DISMISS_FRACTION = 0.25
export const FLING_PX_PER_MS = 0.5
export const SWIPE_COMMIT_FRACTION = 0.35

const ORDER: Detent[] = ["content", "medium", "large"]

export function sheetRelease({
  dy,
  velocity,
  height,
  detent,
  detents,
  dismissible,
}: {
  dy: number
  velocity: number
  height: number
  detent: Detent
  detents: readonly Detent[]
  dismissible: boolean
}): { kind: "dismiss" } | { kind: "snap"; detent: Detent } {
  const sorted = ORDER.filter((d) => detents.includes(d))
  const i = sorted.indexOf(detent)
  const far = Math.abs(dy) > height * DISMISS_FRACTION
  const fling = Math.abs(velocity) > FLING_PX_PER_MS
  if (dy > 0 && (far || fling)) {
    if (i > 0) return { kind: "snap", detent: sorted[i - 1] }
    return dismissible ? { kind: "dismiss" } : { kind: "snap", detent }
  }
  if (dy < 0 && (far || fling) && i < sorted.length - 1) return { kind: "snap", detent: sorted[i + 1] }
  return { kind: "snap", detent }
}

export function swipeBackRelease({
  dx,
  velocity,
  width,
}: {
  dx: number
  velocity: number
  width: number
}): "commit" | "cancel" {
  if (dx <= 0) return "cancel"
  // Floor: pointer deltas are whole px, so 35% of 390 (136.5) commits at 136.
  return dx >= Math.floor(width * SWIPE_COMMIT_FRACTION) || velocity > FLING_PX_PER_MS ? "commit" : "cancel"
}

/*
 * Native frame sheets and swipe-back: release decisions, pure (D10).
 * Units: px and px/ms; positive dy is downward, positive dx is away from the
 * leading edge (callers multiply by the RTL sign first).
 */
export type Detent = "content" | "medium" | "large"

export const DISMISS_FRACTION = 0.25
export const FLING_PX_PER_MS = 0.5
export const SWIPE_COMMIT_FRACTION = 0.35
/** Release velocity is measured over the last 100ms of movement (preview variant-a.js:698). */
export const VELOCITY_WINDOW_MS = 100

/** A pointer sample: timestamp (ms) and clientY (px). */
export type PointerSample = readonly [t: number, y: number]

/** Drop samples older than the velocity window, keeping the newest. */
export function trimSamples(samples: readonly PointerSample[], now: number): PointerSample[] {
  return samples.filter(([t]) => now - t <= VELOCITY_WINDOW_MS)
}

/** px/ms from the oldest windowed sample to the release point; 0 when no time has passed. */
export function releaseVelocity(samples: readonly PointerSample[], t: number, y: number): number {
  const first = trimSamples(samples, t)[0]
  if (!first || t - first[0] <= 0) return 0
  return (y - first[1]) / (t - first[0])
}

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

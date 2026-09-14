/*
 * Task 8 (B5b) · scanner pipeline, stage 5: auto-capture stability gate.
 *
 * `CameraCapture.tsx`'s rAF loop keeps a rolling window of recent
 * `frameDelta` readings (stage 1). `stabilityDecision` fires "capture" only
 * once the frame has genuinely stopped moving (every recent delta at or
 * below `maxDelta`) AND a document quad was actually found — a rock-steady
 * camera pointed at a blank wall must never auto-capture just because
 * nothing moved.
 */

export interface StabilityOptions {
  /** Max per-frame luma delta still counted as "steady". */
  maxDelta?: number
  /** How many of the most recent deltas must all be steady. */
  frames?: number
}

const DEFAULT_MAX_DELTA = 2.5
const DEFAULT_FRAMES = 3

export function stabilityDecision(
  deltas: readonly number[],
  quadFound: boolean,
  options?: StabilityOptions,
): "capture" | "hold" {
  if (!quadFound) return "hold"

  const maxDelta = options?.maxDelta ?? DEFAULT_MAX_DELTA
  const frames = options?.frames ?? DEFAULT_FRAMES
  if (deltas.length < frames) return "hold"

  const recent = deltas.slice(-frames)
  return recent.every((delta) => delta <= maxDelta) ? "capture" : "hold"
}

/** 0..1, with NaN and infinities as 0. */
export function clamp01(value: number): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0
}

/** Mock ring4 (32px: r 13, stroke 4.5, dash 23 of each 27.2 third), scaled. */
export function goldRingGeometry(size: number) {
  const r = (size * 13) / 32
  const stroke = (size * 4.5) / 32
  const circumference = 2 * Math.PI * r
  const third = circumference / 3
  return { r, stroke, circumference, third, dash: third * (23 / 27.2) }
}

export function goldRingDone(parts: readonly number[]): number {
  return parts.filter((p) => clamp01(p) >= 1).length
}

/** Mock level ring (92px: r 42, stroke 6), scaled. */
export function keyRingGeometry(size: number) {
  const r = (size * 42) / 92
  const stroke = (size * 6) / 92
  return { r, stroke, circumference: 2 * Math.PI * r }
}

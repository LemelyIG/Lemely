import { clamp01 } from "./rings"

/** The combo chip is hidden below 2 (mock pr.js runTop). Junk counts (NaN, negative, infinite) never show. */
export function comboVisible(count: number): boolean {
  return Number.isFinite(count) && count >= 2
}

/** The chip bumps only when the count rises. */
export function comboRose(previous: number, next: number): boolean {
  return next > previous
}

/** xp over nextXp, 0..1. No next level (0), NaN and negative xp all read as an empty bar, never NaN. */
export function levelFraction(xp: number, nextXp: number): number {
  if (!Number.isFinite(xp) || !Number.isFinite(nextXp) || nextXp <= 0) return 0
  return clamp01(xp / nextXp)
}

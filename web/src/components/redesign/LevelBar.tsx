/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { levelFraction } from "./game"
import "./redesign.css"

/** Level, a gold XP bar and "240 / 500 XP" (mock .lvl2 / .lb). Gold because XP is earned. */
export function LevelBar({ level, xp, nextXp }: { level: number; xp: number; nextXp: number }) {
  const have = Number.isFinite(xp) ? Math.max(0, Math.round(xp)) : 0
  const need = Number.isFinite(nextXp) ? Math.max(0, Math.round(nextXp)) : 0
  const lv = Number.isFinite(level) ? Math.max(1, Math.round(level)) : 1
  // No next level (top of the ladder): no invented goal, so the text drops "/ N", aria-valuemax follows xp and the
  // bar is full (valuenow equals valuemax), so what is drawn agrees with what is announced.
  const max = need > 0 ? need : Math.max(have, 1)
  const pct = need > 0 ? Math.round(levelFraction(have, need) * 100) : have > 0 ? 100 : 0
  return (
    <div className="rd-level">
      <b>{`Level ${lv}`}</b>
      <span
        className="rd-level-bar"
        role="progressbar"
        aria-label={`Level ${lv}`}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={Math.min(have, max)}
        aria-valuetext={need > 0 ? `${have} of ${need} XP` : `${have} XP`}
      >
        <i style={{ width: `${pct}%` }} />
      </span>
      <small>{need > 0 ? `${have} / ${need} XP` : `${have} XP`}</small>
    </div>
  )
}

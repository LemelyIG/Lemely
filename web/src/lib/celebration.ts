/*
 * The celebration register, DESIGN.md §9.3 — the arithmetic half.
 *
 * §9.3 reserves expressive motion for five moments and nothing else: XP
 * gained, a streak milestone, a leaderboard climb, a correct answer, and the
 * marked-paper result reveal. Until this file, the register existed only as a
 * paragraph of prose and four unused tokens (`--ease-celebrate`,
 * `--dur-celebrate`); `PaperResult.tsx` recorded the reason it deliberately did
 * not build one first ("building a count-up here would set the register from
 * one surface before the spec for it exists in code"). This is that spec.
 *
 * Pure functions live here so the rules can be tested without a DOM; the
 * components that use them are in `components/ui/celebration.tsx`.
 *
 * Three rules are load-bearing and each is pinned by a test:
 *
 * 1. **A count-up never displays a number the student has not earned.**
 *    `--ease-celebrate` is `cubic-bezier(0.18, 1.5, 0.5, 1)`, whose y
 *    overshoots 1. On a *scale* that overshoot is the spring, and it is what
 *    §9.3 asks for. On a *number* it would render 1,240 XP for a few frames on
 *    the way to 1,180 — a figure the account never held, arriving on the one
 *    screen whose whole promise is "this measures work actually done". So the
 *    easing is shared but the number's progress is clamped to [0, 1] and the
 *    value is monotonically non-decreasing.
 *
 * 2. **Reduced motion means the final value immediately** (§9.4), not a
 *    missing number. The global `prefers-reduced-motion` rule in index.css
 *    flattens CSS durations, and a JS count-up is invisible to it — a
 *    stylesheet cannot reach a `requestAnimationFrame` loop. So the media
 *    query is read here as well. Forgetting this is how "reduced motion" turns
 *    into "reduced motion everywhere except the one animation written in
 *    JavaScript".
 *
 * 3. **Never on a failure, and never for engagement alone.** A drop in a value
 *    does not celebrate — it is shown plainly and at once. `isCelebratory`
 *    encodes that: only an increase earns the register.
 */

/** The five moments §9.3 permits. Anything not on this list does not celebrate. */
export type CelebrationMoment =
  | "xp_gained"
  | "streak_milestone"
  | "leaderboard_climb"
  | "correct_answer"
  | "result_reveal"

/**
 * Whether a change earns the celebration register.
 *
 * Only an increase. §9.3's last bullet bans celebrating engagement rather than
 * achievement, and its "never on a failure" rule means a value that fell gets
 * calm treatment, not a quieter version of the same flourish. A value that did
 * not move is not an event at all.
 */
export function isCelebratory(previous: number | null, next: number): boolean {
  if (previous === null) return false
  return next > previous
}

/* ── Easing ─────────────────────────────────────────────────────────────── */

/**
 * y at x for a cubic Bézier with fixed endpoints (0,0) and (1,1).
 *
 * Solves x(t) = x for t by Newton-Raphson with a bisection fallback, then
 * evaluates y(t) — the same thing a browser does for `cubic-bezier()`. Written
 * out rather than approximated because the whole point of a shared register is
 * that the JS count-up and the CSS scale are driven by the *same* curve; two
 * near-misses would read as two different flourishes on one screen.
 */
export function cubicBezier(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  x: number,
): number {
  if (x <= 0) return 0
  if (x >= 1) return 1

  const curve = (a: number, b: number, t: number) => {
    const inverse = 1 - t
    return 3 * inverse * inverse * t * a + 3 * inverse * t * t * b + t * t * t
  }
  const slope = (a: number, b: number, t: number) => {
    const inverse = 1 - t
    return (
      3 * inverse * inverse * a +
      6 * inverse * t * (b - a) +
      3 * t * t * (1 - b)
    )
  }

  let t = x
  for (let i = 0; i < 8; i += 1) {
    const error = curve(x1, x2, t) - x
    if (Math.abs(error) < 1e-6) return curve(y1, y2, t)
    const derivative = slope(x1, x2, t)
    // A flat segment makes Newton's step explode; hand over to bisection.
    if (Math.abs(derivative) < 1e-6) break
    t -= error / derivative
  }

  let low = 0
  let high = 1
  t = x
  for (let i = 0; i < 24; i += 1) {
    const value = curve(x1, x2, t)
    if (Math.abs(value - x) < 1e-6) break
    if (value > x) high = t
    else low = t
    t = (low + high) / 2
  }
  return curve(y1, y2, t)
}

/** `--ease-celebrate`, the §9.1 token. Overshoots above 1 on purpose. */
export function easeCelebrate(t: number): number {
  return cubicBezier(0.18, 1.5, 0.5, 1, t)
}

/**
 * The count-up's progress: `easeCelebrate` with the overshoot clamped away.
 *
 * See rule 1 in this file's header. The spring is kept for the scale, where a
 * value above 1 is a physical overshoot; on a number it would be a fabricated
 * figure.
 */
export function countUpProgress(t: number): number {
  return Math.min(1, Math.max(0, easeCelebrate(Math.min(1, Math.max(0, t)))))
}

/**
 * The integer to display `elapsed` ms into a count from `from` to `to`.
 *
 * Rounds rather than truncates so the final frame lands exactly on `to`, and
 * clamps in both directions so no frame can read above the target or below the
 * starting value.
 */
export function countUpValue(
  from: number,
  to: number,
  elapsed: number,
  duration: number,
): number {
  if (duration <= 0 || elapsed >= duration) return to
  const eased = countUpProgress(elapsed / duration)
  const value = Math.round(from + (to - from) * eased)
  return to >= from
    ? Math.min(to, Math.max(from, value))
    : Math.max(to, Math.min(from, value))
}

/* ── Streak milestones ──────────────────────────────────────────────────── */

/**
 * The streak lengths that earn a sticker, DESIGN.md §8 item 4.
 *
 * A fixed early ladder then every fiftieth day. Deliberately sparse: a badge
 * that arrives every day is wallpaper, and §9.3's ban on celebrating
 * engagement is easiest to breach by lowering this bar until the flourish
 * fires for showing up. Day 1 is not on the ladder for exactly that reason.
 */
const MILESTONE_LADDER = [3, 7, 14, 21, 30, 50, 75, 100]

export function isStreakMilestone(days: number): boolean {
  if (!Number.isInteger(days) || days <= 0) return false
  if (MILESTONE_LADDER.includes(days)) return true
  return days > 100 && days % 50 === 0
}

/**
 * The most recent milestone reached at `days`, or `null` before the first.
 *
 * Used for the sticker a student *holds*, as distinct from the flourish that
 * fires the moment they reach one. The badge persists between milestones; the
 * motion does not.
 */
export function lastStreakMilestone(days: number): number | null {
  if (!Number.isInteger(days) || days <= 0) return null
  if (days > 100) {
    const floored = Math.floor(days / 50) * 50
    return floored >= 100 ? floored : 100
  }
  let best: number | null = null
  for (const step of MILESTONE_LADDER) {
    if (step <= days) best = step
  }
  return best
}

/* ── Environment ────────────────────────────────────────────────────────── */

/**
 * `prefers-reduced-motion: reduce`, read at call time rather than cached.
 *
 * Not cached because the setting can change while the tab is open, and a
 * cached `false` from load would keep animating for a student who turned it on
 * mid-session — the one person most likely to have done so deliberately.
 * Returns `true` when `matchMedia` is unavailable: the safe default for a
 * motion decision is not to move.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return true
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

import { useEffect, useRef, useState } from "react"
import type { HTMLAttributes, ReactNode } from "react"
import { cn } from "@/lib/utils"
import {
  countUpValue,
  isCelebratory,
  lastStreakMilestone,
  prefersReducedMotion,
} from "@/lib/celebration"

/*
 * C-26 · The celebration register, DESIGN.md §9.3 — the rendered half.
 * Arithmetic and the rules that govern it are in `lib/celebration.ts`; read
 * that file's header first, it is where the reasoning lives.
 *
 * Three properties this file is responsible for, none of them cosmetic:
 *
 * **Nothing here blocks input** (§9.2, §9.3). The flourish is
 * `pointer-events-none` and absolutely positioned out of flow, the count-up
 * mutates text inside an element that keeps its own size, and no control is
 * disabled while either runs. A student who taps straight through a
 * celebration is never waiting on it.
 *
 * **Nothing here celebrates a failure or an arrival** (§9.3). `Celebrate`
 * fires only when a value it is already watching *increases*; a first render
 * is not an event, which is why a fresh mount and a page refresh are silent.
 * That is deliberate and it is the whole difference between marking a win and
 * congratulating someone for opening the app.
 *
 * **The numbers stay readable while they move.** Count-ups render in the data
 * face with `tabular-nums` (§4), so the digits do not reflow frame by frame,
 * and the element is `aria-live="off"` with the final value exposed to
 * assistive technology once — a per-frame live region would read a hundred
 * numbers aloud to announce one.
 */

/* ── Count-up ───────────────────────────────────────────────────────────── */

const COUNT_UP_MS = 900 // --dur-celebrate

/**
 * The displayed value of a number counting up to `target`.
 *
 * Interruptible in the sense §9.3 means it: a target that changes mid-flight
 * restarts from whatever is currently on screen rather than snapping back to
 * the start, so a second award landing during the first one's animation reads
 * as one continuous climb.
 *
 * A first observation never animates *unless the caller supplies `from`*. By
 * default there is no honest origin for one — the student's total did not just
 * go from zero to 1,180, that is simply what it has been since before this
 * screen mounted, and animating it would stage a gain that did not happen on
 * this visit.
 *
 * **`from` is the deliberate exception, and it has exactly one honest use.**
 * P5.2 needed §9.3's "marked-paper result reveal", where the value genuinely
 * did arrive while the student watched: they uploaded a script, waited through
 * the marking, and the mark went from unknown to 63 in front of them. That is
 * an event, not a total that was already true. It is gated on the *live* result
 * path for exactly that reason — opening the same paper later from the history
 * table is the "already true since yesterday" case this rule exists for, and it
 * does not pass `from`.
 *
 * Do not reach for `from` to make a number feel livelier. If the value did not
 * change while this reader was looking at it, animating it is a small lie.
 */
export function useCountUp(target: number, from?: number): number {
  const [displayed, setDisplayed] = useState(() => from ?? target)
  const previous = useRef<number | null>(from ?? null)
  const frame = useRef<number | null>(null)

  useEffect(() => {
    const from = previous.current
    previous.current = target

    // First observation, a decrease, or no change: show the truth at once.
    if (!isCelebratory(from, target) || prefersReducedMotion()) {
      setDisplayed(target)
      return
    }

    // Resume from what is on screen, not from the old target — see above.
    const start = performance.now()
    const origin = displayed
    const step = (now: number) => {
      const value = countUpValue(origin, target, now - start, COUNT_UP_MS)
      setDisplayed(value)
      if (value !== target) frame.current = requestAnimationFrame(step)
    }
    frame.current = requestAnimationFrame(step)

    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current)
    }
    // `displayed` is read as the resume point but must not re-trigger the
    // effect, or every frame would start a new animation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target])

  return displayed
}

export interface CountUpProps extends Omit<HTMLAttributes<HTMLSpanElement>, "children"> {
  value: number
  /**
   * An explicit starting value, so the very first render animates.
   *
   * Only for a value that genuinely arrived while this reader watched. See
   * `useCountUp`'s docstring — the default (no animation on first observation)
   * is the honest behaviour and this is the narrow exception to it.
   */
  from?: number
  /** Rendered around the number, e.g. a thousands separator format. */
  format?: (value: number) => string
}

/**
 * A number that counts up when it grows, and simply changes when it does not.
 *
 * The accessible name carries the *target*, never the animating value: a
 * screen reader should hear the number the student earned, once, not a
 * transcript of the animation.
 */
export function CountUp({ value, from, format, className, ...props }: CountUpProps) {
  const displayed = useCountUp(value, from)
  const render = format ?? ((n: number) => n.toLocaleString())
  return (
    <span className={cn("tabular-nums", className)} {...props}>
      <span aria-hidden="true">{render(displayed)}</span>
      <span className="sr-only">{render(value)}</span>
    </span>
  )
}

/* ── Celebrate ──────────────────────────────────────────────────────────── */

export interface CelebrateProps {
  /**
   * The value being watched. A celebration fires when it increases, never on
   * the first observation and never when it falls (§9.3).
   */
  value: number
  className?: string
  children: ReactNode
}

/**
 * Wraps a figure or badge so it springs (1 → 1.08 → 1) and, optionally, springs
 * when its value grows. No confetti (PRODUCT.md anti-reference).
 *
 * The wrapper is `inline-block` and `relative` so the scale has an origin, but it introduces no layout of its
 * own: the spring is a `transform`, so it cannot move anything around it (§9.2).
 */
export function Celebrate({
  value,
  className,
  children,
}: CelebrateProps) {
  const previous = useRef<number | null>(null)
  const [celebrating, setCelebrating] = useState(false)

  useEffect(() => {
    const from = previous.current
    previous.current = value
    if (!isCelebratory(from, value)) return
    setCelebrating(true)
    const timer = setTimeout(() => setCelebrating(false), 1100)
    return () => clearTimeout(timer)
  }, [value])

  return (
    <span className={cn("relative inline-block", className)}>
      <span className={cn("relative inline-block", celebrating && "lm-pop")}>
        {children}
      </span>
    </span>
  )
}

/* ── Milestone chip ─────────────────────────────────────────────────────── */

/**
 * The streak milestone a student currently holds, as a chip.
 *
 * Decorative: the streak itself is stated as a plain number beside it, so
 * nothing here is the only channel a fact arrives on. Renders nothing below the
 * first milestone rather than an empty or "0 days" badge.
 */
export function MilestoneSticker({
  streakDays,
  className,
}: {
  streakDays: number
  className?: string
}) {
  const milestone = lastStreakMilestone(streakDays)
  if (milestone === null) return null
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-chip bg-secondary-container px-2.5 py-1 text-eyebrow text-on-secondary-container",
        className,
      )}
    >
      {milestone} day milestone
    </span>
  )
}

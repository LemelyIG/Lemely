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
 * A first observation never animates. There is no honest "from" for it — the
 * student's total did not just go from zero to 1,180, that is simply what it
 * has been since before this screen mounted, and animating it would stage a
 * gain that did not happen on this visit.
 */
export function useCountUp(target: number): number {
  const [displayed, setDisplayed] = useState(target)
  const previous = useRef<number | null>(null)
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
export function CountUp({ value, format, className, ...props }: CountUpProps) {
  const displayed = useCountUp(value)
  const render = format ?? ((n: number) => n.toLocaleString())
  return (
    <span className={cn("tabular-nums", className)} {...props}>
      <span aria-hidden="true">{render(displayed)}</span>
      <span className="sr-only">{render(value)}</span>
    </span>
  )
}

/* ── Flourish ───────────────────────────────────────────────────────────── */

/**
 * The confetti pieces: a fixed table, never `Math.random()`.
 *
 * Random pieces would make every render of this component visually unique,
 * which defeats `capture_surface.mjs`'s duplicate-hash check (two states that
 * must differ are compared by hash, and two that must *match* would never
 * match) and makes any visual regression on this surface unreviewable. Twelve
 * pieces, paper-and-pastel per §9.3, spread by hand so the fan looks scattered
 * without being random.
 */
const CONFETTI = [
  { x: -64, y: -38, rotate: -38, tone: "bg-pastel-rose", delay: 0 },
  { x: -44, y: -56, rotate: 22, tone: "bg-pastel-amber", delay: 40 },
  { x: -22, y: -64, rotate: -14, tone: "bg-pastel-sage", delay: 10 },
  { x: -6, y: -70, rotate: 46, tone: "bg-pastel-sky", delay: 60 },
  { x: 14, y: -66, rotate: -28, tone: "bg-pastel-lilac", delay: 20 },
  { x: 34, y: -54, rotate: 34, tone: "bg-pastel-clay", delay: 70 },
  { x: 54, y: -40, rotate: -20, tone: "bg-pastel-rose", delay: 30 },
  { x: 68, y: -18, rotate: 52, tone: "bg-pastel-amber", delay: 50 },
  { x: -70, y: -12, rotate: 16, tone: "bg-pastel-sky", delay: 80 },
  { x: -34, y: -24, rotate: -46, tone: "bg-pastel-sage", delay: 90 },
  { x: 26, y: -28, rotate: 12, tone: "bg-pastel-lilac", delay: 100 },
  { x: 46, y: -8, rotate: -34, tone: "bg-pastel-clay", delay: 110 },
]

/**
 * A brief paper-and-pastel flourish, centred on its positioned parent.
 *
 * Renders nothing at all under reduced motion (§9.4: "Confetti does not run"),
 * and nothing when inactive, so the DOM carries no decorative litter between
 * celebrations. `aria-hidden` because it means nothing: every celebration in
 * this product also states its news in words, and a flourish that carried
 * information alone would be meaning by decoration.
 */
export function Flourish({ active }: { active: boolean }) {
  const [running, setRunning] = useState(false)

  useEffect(() => {
    if (!active || prefersReducedMotion()) return
    setRunning(true)
    const timer = setTimeout(() => setRunning(false), 1100)
    return () => clearTimeout(timer)
  }, [active])

  if (!running) return null

  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-visible"
    >
      {CONFETTI.map((piece, index) => (
        <span
          key={index}
          className={cn(
            // `radius-sm`, the smallest rung §6 defines. An earlier cut used a
            // one-pixel arbitrary radius for a crisper paper-scrap edge and the
            // token gate rejected it, correctly: a one-off radius on a
            // decorative element is still a value outside the scale. (The gate
            // reads comments too, so this note cannot spell the old value out —
            // which is a fair rule, since a literal in a comment is exactly how
            // one gets copied back into the code below it.)
            "lm-confetti absolute start-1/2 top-1/2 h-1.5 w-1.5 rounded-sm",
            piece.tone,
          )}
          style={
            {
              "--lm-cx": `${piece.x}px`,
              "--lm-cy": `${piece.y}px`,
              "--lm-cr": `${piece.rotate}deg`,
              animationDelay: `${piece.delay}ms`,
            } as React.CSSProperties
          }
        />
      ))}
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
  /** Suppresses the flourish, keeping the spring. For quieter moments. */
  flourish?: boolean
  className?: string
  children: ReactNode
}

/**
 * Wraps a figure or badge so it springs (1 → 1.08 → 1) and, optionally, throws
 * a flourish when its value grows.
 *
 * The wrapper is `inline-block` and `relative` so the confetti has something to
 * be centred on and the scale has an origin, but it introduces no layout of its
 * own: the spring is a `transform`, so it cannot move anything around it (§9.2).
 */
export function Celebrate({
  value,
  flourish = true,
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
      {/* `flourish` gates only the confetti; the spring below always runs.
          An earlier cut of this component accepted the prop, documented it,
          and never read it — so `flourish={false}` on the training log's XP
          total was throwing confetti anyway. That is P4.2's first lesson
          (a component's docstring stating a rule the component breaks), and it
          was caught by `tsc`'s unused-parameter check rather than by anything
          looking at the screen. */}
      {celebrating && flourish ? <Flourish active /> : null}
      {/* The flourish is rendered first and this second, so both being
          positioned puts the figure above the confetti by DOM order alone. No
          `z-*` utility: §7's z-index scale is a gate, and a raw `z-1` outside
          the scale is exactly what that gate exists to catch. */}
      <span className={cn("relative inline-block", celebrating && "lm-pop")}>
        {children}
      </span>
    </span>
  )
}

/* ── Milestone sticker ──────────────────────────────────────────────────── */

/**
 * The streak milestone a student currently holds, as a §8 sticker badge.
 *
 * This is the first call site of `.sticker` in the product. §8 item 4 permits
 * its ±2° rotation on "genuinely decorative badges, never on a status chip
 * that must be scanned", and a milestone is exactly the former: the streak
 * itself is stated as a plain number beside it, so nothing here is the only
 * channel a fact arrives on. Renders nothing below the first milestone rather
 * than an empty or "0 days" badge.
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
        "sticker inline-flex items-center gap-1 rounded-sm bg-pastel-amber px-2.5 py-1 text-eyebrow text-pastel-amber-ink",
        className,
      )}
    >
      {milestone} day milestone
    </span>
  )
}

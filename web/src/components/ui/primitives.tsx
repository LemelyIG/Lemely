/* Hallmark · pre-emit critique: P4 H3 E4 S4 R4 V3 */
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * P4.1 token migration only — every change below is value-preserving (the
 * build-era aliases already resolve to these same tokens), so no screen still
 * on this file changes appearance.
 *
 * `Eyebrow` is the deliberate exception left alone: DESIGN.md §4.2 puts the
 * `eyebrow` rung in Geist, not mono, and this component is mono. Changing the
 * *face* would restyle a dozen screens this surface does not gate and cannot
 * see, which is the opposite of the surface-at-a-time rule. It moves when a
 * surface that renders it is the one under review.
 */

/** Mono uppercase eyebrow / metadata label (mock: t3, tracked, 10.5–11px). */
export function Eyebrow({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "font-mono text-3xs tracking-widest uppercase text-ink-faint",
        className,
      )}
      {...props}
    />
  )
}

/** Newsreader display heading. (Was documented as Instrument Serif, which
 * DESIGN.md §4 replaced — and was in fact rendering neither, because the
 * `font-serif` class it used has never been a token in this system and
 * resolved to Tailwind's default Georgia stack.) */
export function Display({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("font-display leading-display text-ink", className)}
      {...props}
    />
  )
}

/** Thin progress/meter bar with a filled portion (mock uses this widely). */
export function Meter({
  value,
  label,
  className,
  fillClassName,
}: {
  /** 0–100 */
  value: number
  /**
   * Accessible name stating what this meter measures and its current value
   * (e.g. "Chemistry mastery: 62%"). Required — a bare 0–100 progressbar
   * has no meaning to a screen-reader user without one (axe's
   * `aria-progressbar-name` rule).
   */
  label: string
  className?: string
  fillClassName?: string
}) {
  return (
    <div
      className={cn("h-1.5 rounded-full bg-paper-sunk overflow-hidden", className)}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div
        className={cn("h-full rounded-full bg-accent", fillClassName)}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  )
}

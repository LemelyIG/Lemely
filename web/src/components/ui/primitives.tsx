/* Hallmark · pre-emit critique: P4 H3 E4 S4 R4 V3 */
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * P4.1 token migration only — every change below is value-preserving (the
 * build-era aliases already resolve to these same tokens), so no screen still
 * on this file changes appearance.
 *
 * `Eyebrow` was the deliberate exception left alone at the time: the retired
 * type scale set the `eyebrow` rung in the UI face, not mono. The v5 ramp
 * (DESIGN.md) makes the eyebrow mono, so this component now matches it.
 */

/** Mono uppercase eyebrow / metadata label (mock: t3, tracked, 10.5–11px). */
export function Eyebrow({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "font-mono text-3xs tracking-widest uppercase text-on-surface-variant",
        className,
      )}
      {...props}
    />
  )
}

/** Display heading in the v5 display face (DESIGN.md: Bricolage Grotesque,
 * 28px and above). Historically documented as Instrument Serif, then
 * Newsreader; the `font-serif` class it once used was never a token here and
 * resolved to Tailwind's default Georgia stack. */
export function Display({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("font-display leading-display text-on-surface", className)}
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
      className={cn("h-1.5 rounded-full bg-surface-container-low overflow-hidden", className)}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div
        className={cn("h-full rounded-full bg-primary", fillClassName)}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  )
}

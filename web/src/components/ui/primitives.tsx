import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/** Mono uppercase eyebrow / metadata label (mock: t3, tracked, 10.5–11px). */
export function Eyebrow({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "font-mono text-3xs tracking-widest uppercase text-t3",
        className,
      )}
      {...props}
    />
  )
}

/** Instrument Serif display heading. */
export function Display({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("font-serif leading-display text-t1", className)}
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
      className={cn("h-1.5 rounded-full bg-surface-2 overflow-hidden", className)}
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

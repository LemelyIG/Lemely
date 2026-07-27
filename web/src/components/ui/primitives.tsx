import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/** Mono uppercase eyebrow / metadata label (mock: t3, tracked, 10.5–11px). */
export function Eyebrow({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3",
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
      className={cn("font-serif leading-[1.1] text-t1", className)}
      {...props}
    />
  )
}

/** Thin progress/meter bar with a filled portion (mock uses this widely). */
export function Meter({
  value,
  className,
  fillClassName,
}: {
  /** 0–100 */
  value: number
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
    >
      <div
        className={cn("h-full rounded-full bg-accent", fillClassName)}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  )
}

import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * C-2 Mark display. "58 / 80" plus percentage, in the two scales the product
 * needs it at: hero (results overview — "the mark is the hero" per
 * LEMELY_UI_SPEC 1.6) and inline (list rows, question rows, subject cards).
 * Numeric figures use JetBrains Mono at the inline size — DESIGN.md reserves
 * mono for exactly this ("conveys precision" in the marking process).
 */

export interface MarkDisplayProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  awarded: number
  available: number
  size?: "hero" | "inline"
  showPercent?: boolean
}

export function MarkDisplay({
  awarded,
  available,
  size = "inline",
  showPercent = true,
  className,
  ...props
}: MarkDisplayProps) {
  const pct = available > 0 ? Math.round((awarded / available) * 100) : 0

  if (size === "hero") {
    return (
      <div
        className={cn("flex items-baseline gap-2.5", className)}
        aria-label={`${awarded} out of ${available} marks, ${pct} percent`}
        {...props}
      >
        <span className="text-display-hero text-t1">{awarded}</span>
        <span className="text-display-md text-t3">/ {available}</span>
        {showPercent && (
          <span className="text-metadata text-t2 bg-surface-2 rounded-full px-2.5 py-1 ml-1">
            {pct}%
          </span>
        )}
      </div>
    )
  }

  return (
    <div
      className={cn("inline-flex items-baseline gap-1.5", className)}
      aria-label={`${awarded} out of ${available} marks, ${pct} percent`}
      {...props}
    >
      <span className="font-mono text-sm font-medium text-t1">
        {awarded}/{available}
      </span>
      {showPercent && <span className="font-mono text-xs text-t3">{pct}%</span>}
    </div>
  )
}

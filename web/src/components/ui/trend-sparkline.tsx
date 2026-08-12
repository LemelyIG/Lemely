import { Minus, TrendDown, TrendUp, type Icon } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * C-8 Trend sparkline. Performance over the last N attempts as a small inline
 * SVG polyline (no charting library — none is installed), always paired with
 * an up/down/flat icon + text read so direction survives greyscale the same
 * way the confidence and mark-state scales must (LEMELY_UI_SPEC 4.10 / PRODUCT
 * accessibility floor: "no meaning carried by colour alone").
 */

export interface TrendSparklineProps {
  /** Chronological series, most recent last. Expected range 0–100 (e.g. percentage per attempt). */
  values: number[]
  width?: number
  height?: number
  className?: string
}

type Direction = "up" | "down" | "flat"

function directionOf(values: number[]): Direction {
  if (values.length < 2) return "flat"
  const delta = values[values.length - 1] - values[0]
  if (delta >= 3) return "up"
  if (delta <= -3) return "down"
  return "flat"
}

const directionMeta: Record<Direction, { icon: Icon; label: string; color: string }> = {
  up: { icon: TrendUp, label: "Improving", color: "text-ok" },
  down: { icon: TrendDown, label: "Declining", color: "text-err" },
  flat: { icon: Minus, label: "Steady", color: "text-t2" },
}

export function TrendSparkline({ values, width = 64, height = 24, className }: TrendSparklineProps) {
  if (values.length === 0) {
    return <span className={cn("text-body-md text-t3", className)}>No attempts yet</span>
  }

  const direction = directionOf(values)
  const meta = directionMeta[direction]
  const Icon = meta.icon

  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const pad = 2
  const points = values
    .map((v, i) => {
      const x =
        values.length === 1 ? width / 2 : (i / (values.length - 1)) * (width - pad * 2) + pad
      const y = height - pad - ((v - min) / range) * (height - pad * 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")

  return (
    <div className={cn("inline-flex items-center gap-2", className)}>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className={meta.color}
        aria-hidden
      >
        <polyline
          points={points}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {values.length === 1 && <circle cx={width / 2} cy={height / 2} r={2} fill="currentColor" />}
      </svg>
      <span className={cn("inline-flex items-center gap-1 text-label-sm", meta.color)}>
        <Icon weight="bold" className="w-3.5 h-3.5" aria-hidden />
        {meta.label}
      </span>
    </div>
  )
}

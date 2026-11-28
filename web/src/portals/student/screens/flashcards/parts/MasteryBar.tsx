/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
import type { MasteryLegendItem, MasteryView } from "../flashcardsView"

/**
 * One colour per segment, shared by the bar and the legend so a swatch can never drift from the
 * fill it names. Known is the success text green. Learning is `primary` (tide in dark, navy in
 * light): the mock's tide `#7fb8e0` is only 1.79:1 on the light track, and `inverse-primary`
 * (tide in light, navy in dark) is 1.16:1 on the dark one. `primary` clears 11.6:1 and 7.5:1.
 * The remainder is the track itself.
 */
const FILL = {
  known: "bg-success-text",
  learning: "bg-primary",
  new: "bg-surface-container-high",
} as const

/**
 * fc.css `.mstr`: 6px (row, max 180px) or 10px (detail, full width).
 *
 * The 2px `gap-0.5` is the track showing through, and it is load-bearing: in dark the known green
 * (luminance .385) and the track (.014) sit 6.8:1 apart, so no single colour can be 3:1 from both
 * of them. Each fill is therefore held 3:1 from the track, and the boundary between fills is the
 * track. A share of zero draws no segment, so a fully known deck has no stray sliver.
 */
export function MasteryBar({ mastery, size = "row" }: { mastery: MasteryView; size?: "row" | "detail" }) {
  return (
    <div
      role="img"
      aria-label={mastery.label}
      className={
        size === "row"
          ? "flex h-1.5 max-w-[180px] gap-0.5 overflow-hidden rounded-[3px] bg-surface-container-high"
          : "flex h-2.5 gap-0.5 overflow-hidden rounded-[5px] bg-surface-container-high"
      }
    >
      {mastery.knownPct > 0 ? (
        <i className={`block h-full ${FILL.known}`} style={{ width: `${mastery.knownPct}%` }} />
      ) : null}
      {mastery.learningPct > 0 ? (
        <i className={`block h-full ${FILL.learning}`} style={{ width: `${mastery.learningPct}%` }} />
      ) : null}
    </div>
  )
}

export function MasteryLegend({ legend }: { legend: readonly MasteryLegendItem[] }) {
  return (
    <div className="flex gap-3.5 text-[13px] font-medium leading-tight text-on-surface-variant">
      {legend.map((item) => (
        <span key={item.key} className="inline-flex items-center gap-1.5">
          <i aria-hidden className={`size-2.5 rounded-[3px] ${FILL[item.key]}`} />
          <span><span className="font-mono">{item.count}</span> {item.label}</span>
        </span>
      ))}
    </div>
  )
}

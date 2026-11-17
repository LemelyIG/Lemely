import type { MasteryView } from "../flashcardsView"

/** fc.css `.mstr`: 6px (row, max 180px) or 10px (detail, full width); known = success, learning = tide. */
export function MasteryBar({ mastery, size = "row" }: { mastery: MasteryView; size?: "row" | "detail" }) {
  return (
    <div
      role="img"
      aria-label={mastery.label}
      className={
        size === "row"
          ? "flex h-1.5 max-w-[180px] overflow-hidden rounded-[3px] bg-surface-container-high"
          : "flex h-2.5 overflow-hidden rounded-[5px] bg-surface-container-high"
      }
    >
      <i className="block h-full bg-success-text" style={{ width: `${mastery.knownPct}%` }} />
      <i className="block h-full bg-inverse-primary" style={{ width: `${mastery.learningPct}%` }} />
    </div>
  )
}

export function MasteryLegend({ legend }: { legend: readonly [string, string, string] }) {
  const swatch = ["bg-success-text", "bg-inverse-primary", "bg-surface-container-high"]
  return (
    <div className="flex gap-3.5 text-[13px] font-medium text-on-surface-variant">
      {legend.map((text, i) => (
        <span key={text} className="inline-flex items-center gap-1.5">
          <i aria-hidden className={`size-2.5 rounded-[3px] ${swatch[i]}`} />
          <span className="font-mono">{text.split(" ")[0]}</span> {text.split(" ").slice(1).join(" ")}
        </span>
      ))}
    </div>
  )
}

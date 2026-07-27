import type { VizColor } from "../data"
import { vizBg } from "./colors"

/** A thin track + filled portion meter (the mock's ubiquitous 6px bar). */
export function Bar({ width, color }: { width: number; color: VizColor }) {
  return (
    <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
      <div
        className={`h-full rounded-full ${vizBg(color)}`}
        style={{ width: `${Math.max(0, Math.min(100, width))}%` }}
      />
    </div>
  )
}

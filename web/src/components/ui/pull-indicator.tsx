/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { ArrowClockwise } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * Task 5 (B4a) · sits above a `usePullToRefresh` scroll container, revealed
 * as the drag translates the container down (`useDragGesture`'s own
 * imperative transform, not this component's concern). Before release the
 * arrow rotates with the pull itself, 0 to 180deg over `progress` — pointing
 * down becomes pointing up, "let go now" read from the icon rather than from
 * a number — then `refreshing` swaps that manual rotation for the
 * continuous `lm-spin` keyframe (index.css §9, first used here) until the
 * caller's `onRefresh` settles. Rotation only, never a resize or an
 * opacity cross-fade between two icons: DESIGN.md §9.2 restricts animation
 * to transform/opacity, and one icon that turns is also just simpler than
 * two icons swapped.
 */

export interface PullIndicatorProps {
  /** 0..1 pull progress from `pullState`. Ignored (opacity pinned to 1)
   * once `refreshing`. */
  progress: number
  refreshing: boolean
}

export function PullIndicator({ progress, refreshing }: PullIndicatorProps) {
  return (
    <div
      role="status"
      aria-label={refreshing ? "Refreshing" : undefined}
      aria-hidden={refreshing ? undefined : true}
      className="flex h-11 w-11 items-center justify-center rounded-full border border-border bg-paper text-t2 shadow-sm"
      style={{ opacity: refreshing ? 1 : progress }}
    >
      <ArrowClockwise
        size={20}
        aria-hidden="true"
        className={cn(refreshing && "motion-safe:animate-[lm-spin_0.8s_linear_infinite]")}
        style={refreshing ? undefined : { transform: `rotate(${progress * 180}deg)` }}
      />
    </div>
  )
}

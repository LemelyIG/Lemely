/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { SkeletonBlock, SkeletonLine } from "@/components/ui/skeleton"
import "./redesign.css"

/**
 * Ghost skeleton rows in the hairline-row geometry. One status region announces "Loading" once; the rows are
 * silent. The pulse is the kit's opacity-only animate-lm-pulse (DESIGN.md §9.2), which the global
 * reduced-motion rule in index.css ends.
 *
 * `announce={false}` makes the rows pure decoration: no status region and hidden from assistive tech. Use it
 * inside a parent that already announces (a skeleton's own status) or beside real empty copy.
 */
export function GhostRows({ rows = 3, withLeading = false, announce = true }: { rows?: number; withLeading?: boolean; announce?: boolean }) {
  return (
    <div
      role={announce ? "status" : undefined}
      aria-label={announce ? "Loading" : undefined}
      aria-hidden={announce ? undefined : true}
      className="rd-ghostrows"
    >
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="rd-ghostrow">
          {withLeading ? <SkeletonBlock announce={false} className="h-9 w-9 flex-none rounded-row bg-surface-container-high" /> : null}
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <SkeletonLine announce={false} width="60%" className="bg-surface-container-high" />
            <SkeletonLine announce={false} width="38%" className="h-3 bg-surface-container-high" />
          </div>
        </div>
      ))}
    </div>
  )
}

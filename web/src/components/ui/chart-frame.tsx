import type { HTMLAttributes, ReactNode } from "react"
import { ChartBar } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * Presentational wrapper for a chart. Nivo is Phase 5 (DESIGN.md §11) — this
 * component only supplies the frame every chart sits inside (title, optional
 * legend slot, surface/border/radius) and the one thing §11 makes mandatory
 * for every chart regardless of library: an empty-data state. Nothing here
 * imports or references `@nivo/*`; the `children` slot is where a future
 * chart renders once Phase 5 wires it in, and until then a screen can pass
 * a `SkeletonBlock` or nothing at all through `children` while `isEmpty` is
 * true.
 *
 * "Empty-data state is mandatory on every chart... with marginalia rather
 * than a blank box" (§11) is enforced structurally, not by convention: there
 * is no `children`-only render path that skips the empty check. If `isEmpty`
 * is true, the empty state renders regardless of what `children` contains,
 * so a chart component can't accidentally render a broken/blank plot area
 * for a dataset that turned out to have zero rows.
 */

export interface ChartFrameProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  /** Chart title, rendered as `display-sm` — matches the sub-section heading
   * rung used elsewhere for card/panel titles. */
  title: ReactNode
  /** One-line supporting context under the title (e.g. "Last 6 weeks"). */
  subtitle?: ReactNode
  /** Legend slot, rendered top-end of the header row. Optional: a
   * single-series chart (§11: "a single-series line uses `--accent`
   * deliberately, since there is no ambiguity with one line") has nothing to
   * key a legend against. */
  legend?: ReactNode
  /** True when the underlying dataset has no rows to plot. Forces the
   * mandatory empty state regardless of what `children` contains. */
  isEmpty?: boolean
  /** Marginalia line for the empty state, e.g. "Nothing marked yet". Caveat
   * per DESIGN.md §4.1 — decorative only, so `emptyBody` below carries the
   * actual explanation for anyone who can't read it. */
  emptyMarginalia?: string
  /** One-sentence explanation of why the chart is empty and, ideally, what
   * fills it. Required whenever `isEmpty` is true — DESIGN.md §12 bans a
   * blank empty state, and a generic default here would just be a blank
   * state with extra steps. */
  emptyBody?: string
  /** Fills the empty state, e.g. "Mark your first paper". */
  emptyAction?: ReactNode
  /** The chart itself (a future Nivo component, or a placeholder while
   * building). Ignored while `isEmpty` is true. */
  children?: ReactNode
}

export function ChartFrame({
  title,
  subtitle,
  legend,
  isEmpty = false,
  emptyMarginalia = "Nothing to plot yet",
  emptyBody,
  emptyAction,
  children,
  className,
  ...props
}: ChartFrameProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4 rounded-lg border border-rule bg-paper-raised p-6",
        className,
      )}
      {...props}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <h3 className="text-display-sm text-ink">{title}</h3>
          {subtitle ? <p className="text-body-sm text-ink-muted">{subtitle}</p> : null}
        </div>
        {legend && !isEmpty ? (
          <div className="flex shrink-0 items-center gap-3 text-body-sm text-ink-muted">
            {legend}
          </div>
        ) : null}
      </div>

      {isEmpty ? (
        <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-paper-sunk">
            <ChartBar size={20} weight="regular" className="text-ink-faint" aria-hidden="true" />
          </div>
          <p className="text-hand text-ink-muted">{emptyMarginalia}</p>
          {emptyBody ? <p className="max-w-xs text-body-sm text-ink-muted">{emptyBody}</p> : null}
          {emptyAction ? <div className="mt-1">{emptyAction}</div> : null}
        </div>
      ) : (
        children
      )}
    </div>
  )
}

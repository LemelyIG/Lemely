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
  /** Marginalia line for the empty state, e.g. "Nothing marked yet".
   * Decorative only, so `emptyBody` below carries the
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
  /**
   * Heading level for the title. Defaults to 3, which is right wherever the
   * chart sits inside a section that already has its own `h2` — which is the
   * case on `ClassAnalytics` and the student `Overview`.
   *
   * P7.1: it is NOT the case on the teacher's student-detail screen, where the
   * trend panel is a top-level section under the page `h1`, so an `h3` skipped
   * a level and axe reported `heading-order`. The visual rung is unchanged
   * either way — `display-sm` is the panel-title size regardless of the tag,
   * because the heading level is a document-structure claim and not a type
   * choice.
   */
  headingLevel?: 2 | 3
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
  headingLevel = 3,
  ...props
}: ChartFrameProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3"
  return (
    <div
      className={cn(
        "flex flex-col gap-4 rounded-lg border border-outline-variant bg-surface-container-lowest p-6",
        className,
      )}
      {...props}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <Heading className="text-display-sm text-on-surface">{title}</Heading>
          {subtitle ? <p className="text-body-sm text-on-surface-variant">{subtitle}</p> : null}
        </div>
        {legend && !isEmpty ? (
          <div className="flex shrink-0 items-center gap-3 text-body-sm text-on-surface-variant">
            {legend}
          </div>
        ) : null}
      </div>

      {isEmpty ? (
        <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-surface-container-low">
            <ChartBar size={20} weight="regular" className="text-on-surface-variant" aria-hidden="true" />
          </div>
          <p className="text-body-sm text-on-surface-variant">{emptyMarginalia}</p>
          {emptyBody ? <p className="max-w-xs text-body-sm text-on-surface-variant">{emptyBody}</p> : null}
          {emptyAction ? <div className="mt-1">{emptyAction}</div> : null}
        </div>
      ) : (
        children
      )}
    </div>
  )
}

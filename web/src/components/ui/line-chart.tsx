/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useMemo } from "react"
import { ResponsiveLine } from "@nivo/line"
import type { Point } from "@nivo/line"
import { useChartAnimation, useNivoTheme } from "@/lib/nivoTheme"
import { SkeletonBlock } from "./skeleton"
import { cn } from "@/lib/utils"

/*
 * C-27 · The product's line chart, DESIGN.md §11.
 *
 * One wrapper, one theme, no chart anywhere setting its own colours. Read
 * `lib/nivoTheme.ts` first — it is where the token resolution and the reasoning
 * behind it live.
 *
 * This component always sits inside `ChartFrame`, which owns the title, the
 * legend slot and §11's mandatory empty state. The split is deliberate: the
 * empty state is a *frame* concern, because a chart component that renders its
 * own empty state can be bypassed by rendering the plot directly, and §11 wants
 * that route closed structurally rather than by convention.
 *
 * Four things here are not styling.
 *
 * **A chart that cannot resolve its tokens does not draw.** `ready` is false
 * until the theme has read real values off the document. The alternative — Nivo
 * falling back to its own defaults — puts a chart on screen in the wrong
 * colours, and a wrong chart is much harder to notice than a missing one. This
 * build has been caught four separate times by a reference that resolved to
 * nothing while everything downstream carried on looking fine.
 *
 * **Points are focusable and labelled.** `isFocusable` plus `pointAriaLabel`
 * makes every datum reachable by keyboard and spoken with its exact values, so
 * the chart is not a mouse-only object. §11 requires tooltips to give exact
 * values; a tooltip alone gives them only to a reader who can hover.
 *
 * **Meaning is never carried by colour alone** (§11, §3.6). A single series is
 * drawn in `--accent`, where there is nothing to distinguish it *from*. Beyond
 * one series the legend is not optional and is rendered unconditionally, and
 * every point states its series name in its accessible label and its tooltip,
 * so the series a datum belongs to is readable without seeing its colour.
 *
 * **Reduced motion means reduced, not broken** (§9.4). `animate={false}` makes
 * react-spring land every value immediately; the chart still arrives, still has
 * axes, tooltips and focusable points, and simply does not transition.
 */

/** One plotted series. `y` may be null for a gap the data genuinely has. */
export interface LineSeries {
  id: string
  data: readonly { x: string; y: number | null }[]
}

export interface LineChartProps {
  series: readonly LineSeries[]
  /** Plot height in px. The width always fills the frame. */
  height?: number
  /** Axis captions. Both optional, because a chart whose frame subtitle
   * already names the units does not need to repeat them on the axis. */
  axisBottomLegend?: string
  axisLeftLegend?: string
  /** Fixed y-domain. Defaults to `auto`, but a percentage chart should pin
   * 0–100 so a flat run of high marks does not fill the panel and read as
   * volatility. */
  yMin?: number | "auto"
  yMax?: number | "auto"
  /** Renders a value for a tooltip, an axis tick and an accessible label.
   * Defaults to the bare number. */
  formatValue?: (value: number) => string
  /** An extra line of context under the value in the tooltip, e.g. a sample
   * size. Returning `null` omits it. */
  tooltipDetail?: (point: LinePointContext) => string | null
  /** Fill under the line. Single-series only: overlapping washes stop being
   * readable the moment there are two. */
  enableArea?: boolean
  /** Accessible name for the plot as a whole. Required: an unlabelled
   * `<svg role="img">` is an anonymous object in a screen reader's list. */
  ariaLabel: string
  className?: string
}

/** What `tooltipDetail` receives: the datum, in the caller's own terms. */
export interface LinePointContext {
  seriesId: string
  x: string
  y: number
}

function contextOf(point: Point<LineSeries>): LinePointContext {
  return {
    seriesId: String(point.seriesId),
    x: String(point.data.x),
    y: Number(point.data.y),
  }
}

export function LineChart({
  series,
  height = 220,
  axisBottomLegend,
  axisLeftLegend,
  yMin = "auto",
  yMax = "auto",
  formatValue = (v) => String(v),
  tooltipDetail,
  enableArea = false,
  ariaLabel,
  className,
}: LineChartProps) {
  const { theme, seriesColors, singleSeriesColor, tokens, ready } = useNivoTheme()
  const animate = useChartAnimation()

  const multi = series.length > 1
  const colors = useMemo(
    () => (multi ? seriesColors : [singleSeriesColor]),
    [multi, seriesColors, singleSeriesColor],
  )

  /*
   * Space for the axes, and nothing more. The left margin has to hold the
   * widest tick label the data face will produce; 44px fits a three-digit
   * percentage at `data-sm` with room for the axis line, and the legend below
   * gets its own band rather than overlapping the ticks.
   *
   * **The right margin is 28px because the last tick label is centred on the
   * last point, which sits on the plot's right edge, so half of it hangs
   * outside.** At 12px it was clipped, and the clipping was the dangerous kind:
   * a cohort trend whose final point fell on 11 August rendered an axis reading
   * "Aug 1". Not a smudge, not an ellipsis — a different, entirely plausible
   * date, ten days out, with nothing to signal it had been cut. The table
   * underneath said "Aug 11, 2026" three lines below. Found by looking at a
   * capture; no assertion in this repo could have seen it.
   */
  const margin = useMemo(
    () => ({
      top: 8,
      right: 28,
      bottom: (axisBottomLegend ? 44 : 28) + (multi ? 28 : 0),
      left: axisLeftLegend ? 56 : 44,
    }),
    [axisBottomLegend, axisLeftLegend, multi],
  )

  if (!ready) {
    // Reserves the exact plot height, so the chart arriving does not shift
    // anything below it (Phase 6.3: skeletons reserve space, CLS < 0.1).
    return <SkeletonBlock className={cn("w-full", className)} style={{ height }} />
  }

  return (
    <div className={cn("w-full", className)} style={{ height }}>
      <ResponsiveLine<LineSeries>
        data={series}
        theme={theme}
        colors={colors}
        margin={margin}
        animate={animate}
        motionConfig="gentle"
        curve="monotoneX"
        xScale={{ type: "point" }}
        yScale={{ type: "linear", min: yMin, max: yMax, stacked: false }}
        // §11: horizontal grid lines only. A vertical grid on a point scale
        // draws one line per datum, which at twelve papers is a picket fence.
        enableGridX={false}
        enableGridY
        lineWidth={2}
        pointSize={7}
        pointColor={tokens["--paper-raised"]}
        pointBorderWidth={2}
        pointBorderColor={{ from: "seriesColor" }}
        enableArea={enableArea && !multi}
        areaOpacity={0.12}
        areaBaselineValue={typeof yMin === "number" ? yMin : 0}
        useMesh
        enableCrosshair
        crosshairType="x"
        axisTop={null}
        axisRight={null}
        axisBottom={{
          tickSize: 0,
          tickPadding: 8,
          legend: axisBottomLegend,
          legendOffset: 36,
          legendPosition: "middle",
        }}
        axisLeft={{
          tickSize: 0,
          tickPadding: 8,
          tickValues: 5,
          format: (value) => formatValue(Number(value)),
          legend: axisLeftLegend,
          legendOffset: -46,
          legendPosition: "middle",
        }}
        legends={
          multi
            ? [
                {
                  anchor: "bottom",
                  direction: "row",
                  translateY: axisBottomLegend ? 56 : 40,
                  itemWidth: 110,
                  itemHeight: 16,
                  itemsSpacing: 8,
                  symbolSize: 8,
                  symbolShape: "circle",
                  itemDirection: "left-to-right",
                },
              ]
            : []
        }
        role="img"
        ariaLabel={ariaLabel}
        isFocusable
        pointAriaLabel={(point) => {
          const ctx = contextOf(point)
          const detail = tooltipDetail?.(ctx)
          const head = multi
            ? `${ctx.seriesId}, ${ctx.x}: ${formatValue(ctx.y)}`
            : `${ctx.x}: ${formatValue(ctx.y)}`
          return detail ? `${head}. ${detail}` : head
        }}
        tooltip={({ point }) => {
          const ctx = contextOf(point)
          const detail = tooltipDetail?.(ctx)
          return (
            <div className="flex flex-col gap-0.5 rounded-sm border border-rule bg-paper-raised px-2.5 py-1.5">
              {/* The series name is text, not a swatch. A tooltip that
                  identified its series by a coloured dot alone would put the
                  one fact a multi-series chart most needs into the colour
                  channel a second time. */}
              {multi ? (
                <span className="text-label text-ink-muted">{ctx.seriesId}</span>
              ) : null}
              <span className="text-data-md text-ink">
                {ctx.x}: {formatValue(ctx.y)}
              </span>
              {detail ? (
                <span className="text-body-sm text-ink-muted">{detail}</span>
              ) : null}
            </div>
          )
        }}
      />
    </div>
  )
}

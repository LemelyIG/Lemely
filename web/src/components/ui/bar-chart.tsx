/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useMemo } from "react"
import { ResponsiveBar } from "@nivo/bar"
import { useChartAnimation, useNivoTheme } from "@/lib/nivoTheme"
import { ChartDataTable } from "./chart-data-table"
import { SkeletonBlock } from "./skeleton"
import { cn } from "@/lib/utils"

/*
 * C-28 · The product's bar chart, DESIGN.md §11. Sibling of `LineChart`; the
 * same theme, the same token-resolution gate, the same reduced-motion path.
 * Read `lib/nivoTheme.ts` and `line-chart.tsx` before this file.
 *
 * The one thing worth stating separately: **a bar encodes its value in height,
 * which is not a colour channel.** That is why this component exists at all
 * rather than a second heat-scale. §11 and §3.6 both forbid meaning carried by
 * colour alone, and an intensity grid — however carefully its bands are named —
 * puts the entire quantity into the one channel a colour-blind reader, a
 * greyscale print and a low-contrast phone screen all degrade first. A bar
 * chart says the same thing in a channel none of them touch.
 */

export interface BarPoint {
  /** Category label. Must be unique within the series: it is the datum's key. */
  label: string
  value: number
}

export interface BarChartProps {
  data: readonly BarPoint[]
  height?: number
  /** Bars run left-to-right instead of bottom-up. Use for long category
   * names, which do not survive a vertical axis on a phone. */
  horizontal?: boolean
  axisBottomLegend?: string
  axisLeftLegend?: string
  /** Renders a value for the tooltip, the axis and the accessible table. */
  formatValue?: (value: number) => string
  /**
   * Per-bar colour, for a chart whose colour is semantic rather than a series
   * key — a grade distribution, where the bar's colour is the grade band and
   * is shared with every `GradeBadge` on the page.
   *
   * Return a resolved colour, never a `var()` string: Nivo hands bar colours
   * to react-spring, which parses them (see `lib/nivoTheme.ts`). Resolved
   * token values are available from `useNivoTheme().tokens`.
   *
   * Defaults to the single-series accent. Do not use this to hand-pick a
   * palette; that is what the shared theme is for.
   */
  colorFor?: (point: BarPoint) => string
  /** Prints the value on the bar. Use where the exact number matters at a
   * glance and the bars are wide enough to hold it. */
  showValues?: boolean
  /** An extra line under the value in the tooltip. `null` omits it. */
  tooltipDetail?: (point: BarPoint) => string | null
  /** Thins the category axis to every Nth label. A 28-day axis is unreadable
   * at one label per bar on a phone; the tooltip and the accessible table
   * still carry every one of them. */
  tickEvery?: number
  ariaLabel: string
  className?: string
}

export function BarChart({
  data,
  height = 220,
  horizontal = false,
  axisBottomLegend,
  axisLeftLegend,
  formatValue = (v) => String(v),
  colorFor,
  showValues = false,
  tooltipDetail,
  tickEvery = 1,
  ariaLabel,
  className,
}: BarChartProps) {
  const { theme, singleSeriesColor, tokens, ready } = useNivoTheme()
  const animate = useChartAnimation()

  const rows = useMemo(
    () => data.map((d) => ({ label: d.label, value: d.value })),
    [data],
  )

  const byLabel = useMemo(() => {
    const map = new Map<string, BarPoint>()
    for (const d of data) map.set(d.label, d)
    return map
  }, [data])

  /*
   * Every Nth category label, by position rather than by value: the caller's
   * labels are dates and codes, not numbers, so there is nothing to compute a
   * tick interval from. An empty list means "no ticks at all", which Nivo
   * distinguishes from `undefined` ("all of them").
   */
  const tickValues = useMemo(() => {
    if (tickEvery <= 1) return undefined
    return rows.filter((_, i) => i % tickEvery === 0).map((r) => r.label)
  }, [rows, tickEvery])

  /*
   * Ticks for the value axis.
   *
   * **A count axis must not be asked for four ticks.** Nivo's `tickValues: 4`
   * divides the domain evenly and hands the fractions to `format`, so a class
   * where the largest grade bucket holds one student produced ticks at 0,
   * 0.25, 0.5, 0.75, 1 — which `Math.round` turned into an axis reading
   * "0 0 0 1 1 1". Every gate passed: the numbers were right, the formatter was
   * right, and the axis was gibberish. Only a rendered capture showed it.
   *
   * So when every value is a whole number (a headcount, a tally, XP), the ticks
   * are the whole numbers themselves, thinned to at most five. Continuous data
   * keeps the even division, which is correct for it.
   */
  const valueTickValues = useMemo(() => {
    if (!data.every((d) => Number.isInteger(d.value))) return 4
    const max = Math.max(0, ...data.map((d) => d.value))
    if (max === 0) return [0]
    const step = Math.max(1, Math.ceil(max / 4))
    const ticks: number[] = []
    for (let v = 0; v <= max; v += step) ticks.push(v)
    return ticks
  }, [data])

  const margin = useMemo(
    () => ({
      top: 8,
      right: 12,
      bottom: axisBottomLegend ? 44 : 28,
      left: axisLeftLegend ? 56 : 44,
    }),
    [axisBottomLegend, axisLeftLegend],
  )

  if (!ready) {
    return <SkeletonBlock className={cn("w-full", className)} style={{ height }} />
  }

  const categoryAxis = {
    tickSize: 0,
    tickPadding: 8,
    tickValues,
    legend: horizontal ? axisLeftLegend : axisBottomLegend,
    legendOffset: horizontal ? -46 : 36,
    legendPosition: "middle" as const,
  }
  const valueAxis = {
    tickSize: 0,
    tickPadding: 8,
    tickValues: valueTickValues,
    format: (value: number | string) => formatValue(Number(value)),
    legend: horizontal ? axisBottomLegend : axisLeftLegend,
    legendOffset: horizontal ? 36 : -46,
    legendPosition: "middle" as const,
  }

  return (
    <div className={cn("w-full", className)} style={{ height }}>
      <ResponsiveBar
        data={rows}
        keys={["value"]}
        indexBy="label"
        theme={theme}
        // A single-key bar chart is a single series, so §11's single-series
        // rule applies and accent is unambiguous here for the same reason it
        // is on a lone line — unless the caller's colour carries meaning of
        // its own, which is what `colorFor` is for.
        colors={
          colorFor
            ? (d) => {
                const label = String(d.indexValue)
                return colorFor(byLabel.get(label) ?? { label, value: Number(d.value ?? 0) })
              }
            : [singleSeriesColor]
        }
        margin={margin}
        animate={animate}
        motionConfig="gentle"
        layout={horizontal ? "horizontal" : "vertical"}
        padding={0.3}
        borderRadius={2}
        enableLabel={showValues}
        label={(d) => formatValue(Number(d.value ?? 0))}
        // Printed inside the bar where it fits, and simply omitted where it
        // does not — a label spilling past a short bar onto the one beside it
        // reads as belonging to the wrong category. The tooltip and the
        // accessible table still carry every value.
        labelSkipWidth={horizontal ? 28 : 0}
        labelSkipHeight={horizontal ? 0 : 18}
        labelTextColor={tokens["--paper-raised"]}
        enableGridX={horizontal}
        enableGridY={!horizontal}
        axisTop={null}
        axisRight={null}
        axisBottom={horizontal ? valueAxis : categoryAxis}
        axisLeft={horizontal ? categoryAxis : valueAxis}
        role="img"
        ariaLabel={ariaLabel}
        /*
         * P6.4: no `isFocusable`, no `barAriaLabel`. Nivo puts both on a bare
         * `<rect>`, and `aria-label` on an element with no role is prohibited
         * ARIA (axe `aria-prohibited-attr`, 28 nodes on this chart alone on
         * `student-profile`) — so it was never dependably announced. It also
         * made every bar a tab stop: 28 presses to get past one panel.
         *
         * The exact values now live in `ChartDataTable` below, which is a real
         * table a screen reader can navigate. See `chart-data-table.tsx`.
         */
        tooltip={({ indexValue, value }) => {
          const label = String(indexValue)
          const detail = tooltipDetail?.(byLabel.get(label) ?? { label, value })
          return (
            <div className="flex flex-col gap-0.5 rounded-sm border border-rule bg-paper-raised px-2.5 py-1.5">
              <span className="text-data-md text-ink">
                {label}: {formatValue(value)}
              </span>
              {detail ? (
                <span className="text-body-sm text-ink-muted">{detail}</span>
              ) : null}
            </div>
          )
        }}
      />
      <ChartDataTable
        caption={ariaLabel}
        columns={[
          axisBottomLegend ?? axisLeftLegend ?? "Category",
          axisLeftLegend ?? axisBottomLegend ?? "Value",
        ]}
        rows={data.map((d) => {
          const detail = tooltipDetail?.(d)
          const value = formatValue(d.value)
          // The tooltip's second line is context a sighted reader gets for
          // free ("3 of 24 students"), so it belongs in the same cell rather
          // than being dropped — this table is the other reader's tooltip.
          return [d.label, detail ? `${value}. ${detail}` : value]
        })}
      />
    </div>
  )
}

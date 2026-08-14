/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Suspense, lazy } from "react"
import type { LineChartProps } from "./line-chart"
import type { BarChartProps } from "./bar-chart"
import { SkeletonBlock } from "./skeleton"
import { cn } from "@/lib/utils"

/*
 * Route-deferred wrappers around the two chart components (P6.3).
 *
 * ── What this is for ───────────────────────────────────────────────────────
 *
 * Lighthouse, measured against a real build of HEAD, reports the same two
 * chunks as unused JavaScript on the student dashboard:
 *
 *     index-*.js       142KB total,  53KB unused
 *     nivoTheme-*.js    72KB total,  50KB unused
 *
 * The second is entirely avoidable. It is reached only through `LineChart` and
 * `BarChart`, both of which were imported statically, so `nivoTheme` plus the
 * `@nivo/*` chunk behind it were downloaded, parsed and evaluated before first
 * paint on every route carrying a chart — for a panel that on all three of
 * those routes sits below the fold. The dashboard is the product's most-visited
 * screen and its Time to Interactive was the worst of the 41 audited routes.
 *
 * ── Why the fallback is a `SkeletonBlock` at the exact plot height ─────────
 *
 * §6.3 asks for skeletons that reserve space, and a lazy boundary is the one
 * place where getting that wrong *creates* the layout shift the same section
 * asks to remove. `line-chart.tsx` already renders exactly this block while it
 * waits for its tokens to resolve, so the deferred and the token-pending states
 * are the same shape at the same height, and neither moves what is under it.
 * `height` carries the same default as the component it stands in for; a
 * divergence there would be invisible in review and visible on screen.
 *
 * ── Why `ClassAnalytics` still imports the eager wrappers ─────────────────
 *
 * It calls `useNivoTheme()` itself, at the screen level, for the weakness
 * heatmap — one of D5.1's four logged §11 exceptions, which is drawn by hand
 * rather than by Nivo but reads its colours from the same theme. That import
 * pulls `nivoTheme` into the route regardless, so wrapping its charts in
 * Suspense would add a boundary and defer nothing. Left alone deliberately
 * rather than changed for symmetry.
 */

const LineChartImpl = lazy(() =>
  import("./line-chart").then((m) => ({ default: m.LineChart })),
)
const BarChartImpl = lazy(() => import("./bar-chart").then((m) => ({ default: m.BarChart })))

/** Matches `LineChart`'s own `height = 220` / `BarChart`'s `height = 220`. */
const DEFAULT_CHART_HEIGHT = 220

function ChartFallback({ height, className }: { height?: number; className?: string }) {
  return (
    <SkeletonBlock
      className={cn("w-full", className)}
      style={{ height: height ?? DEFAULT_CHART_HEIGHT }}
    />
  )
}

export function LineChart(props: LineChartProps) {
  return (
    <Suspense fallback={<ChartFallback height={props.height} className={props.className} />}>
      <LineChartImpl {...props} />
    </Suspense>
  )
}

export function BarChart(props: BarChartProps) {
  return (
    <Suspense fallback={<ChartFallback height={props.height} className={props.className} />}>
      <BarChartImpl {...props} />
    </Suspense>
  )
}

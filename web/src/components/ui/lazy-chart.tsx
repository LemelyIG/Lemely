/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Suspense, lazy } from "react"
import type { LineChartProps } from "./line-chart"
import type { BarChartProps } from "./bar-chart"
import { SkeletonBlock } from "./skeleton"
import { ErrorBoundary } from "./error-boundary"
import { ErrorState } from "./state-views"
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
 *
 * ── PR 1B: an `ErrorBoundary` around each chunk, not just a `Suspense` ─────
 *
 * `@nivo/*` renders SVG from whatever data a screen hands it; a shape it does
 * not expect (an empty series, a NaN slipped through a bad average) throws
 * during Nivo's own render, same as any other component. Before this, that
 * throw had nothing between it and the portal's `<Outlet/>` boundary (see
 * `portals/*\/index.tsx`), so a broken chart on a dashboard that also shows
 * three unrelated panels blanked the whole screen instead of just the chart.
 * `ErrorState` renders `compact`, matching `ChartFallback`'s `height` on its
 * own wrapper `<div>` so the failure state occupies the same box the chart or
 * its loading skeleton would have — a failed chart must not reflow whatever
 * sits below it on the page.
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

/**
 * What renders in place of a chart that threw. Fixed to the same `height` as
 * `ChartFallback` (and the chart it stands in for), so a reader scrolling a
 * dashboard never sees the layout jump the moment one panel fails. `compact`
 * keeps `ErrorState` to the left-aligned inline treatment rather than the
 * centred full-panel one — the latter's own min height (`py-12` plus a 48px
 * icon) does not reliably fit inside a 220px chart box at every width.
 *
 * `onRetry` wires to the `ErrorBoundary`'s own `reset`, passed through as
 * `action` rather than dropped: a chart can fail on one bad render (a stale
 * average that briefly went NaN, an empty series mid-refetch) and recover on
 * the next, and a fallback with no way back forces a full page reload to
 * find out — the one recovery path `ErrorBoundary.reset` exists for.
 */
function ChartErrorFallback({
  height,
  className,
  onRetry,
}: {
  height?: number
  className?: string
  onRetry: () => void
}) {
  return (
    <div className={cn("w-full overflow-hidden", className)} style={{ height: height ?? DEFAULT_CHART_HEIGHT }}>
      <ErrorState
        compact
        heading="This chart failed to load"
        className="h-full"
        action={{ label: "Try again", onClick: onRetry }}
      />
    </div>
  )
}

export function LineChart(props: LineChartProps) {
  return (
    <ErrorBoundary
      fallback={(_error, reset) => (
        <ChartErrorFallback height={props.height} className={props.className} onRetry={reset} />
      )}
    >
      <Suspense fallback={<ChartFallback height={props.height} className={props.className} />}>
        <LineChartImpl {...props} />
      </Suspense>
    </ErrorBoundary>
  )
}

export function BarChart(props: BarChartProps) {
  return (
    <ErrorBoundary
      fallback={(_error, reset) => (
        <ChartErrorFallback height={props.height} className={props.className} onRetry={reset} />
      )}
    >
      <Suspense fallback={<ChartFallback height={props.height} className={props.className} />}>
        <BarChartImpl {...props} />
      </Suspense>
    </ErrorBoundary>
  )
}

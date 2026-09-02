/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect } from "react"
import { isRouteErrorResponse, useRouteError } from "react-router-dom"
import { FullPageState } from "@/portals/misc/FullPageState"
import { classifyRouteError, type RouteFailure } from "@/lib/routeError"
import { useOnlineStatus } from "@/lib/online"
import { handleChunkError } from "@/lib/staleChunk"
import { reportClientError } from "@/lib/clientErrors"
import { useCountdown } from "@/lib/hooks/useCountdown"
import { useServiceHealth } from "@/lib/hooks/useServiceHealth"

/*
 * PR 2 part A2 · which full-page state a route-level failure renders, wired
 * to the real browser.
 *
 * `classifyRouteError` (`lib/routeError.ts`) is the pure decision; everything
 * here is the plumbing that decision needs to run for real: `useRouteError`
 * for the thrown value, `useOnlineStatus` for connectivity, `handleChunkError`
 * as the reload attempt, and `useCountdown`/`useServiceHealth` for the two
 * variants that keep changing after the first render.
 *
 * Two exports, two mounting shapes, one classification:
 *  - `RouteErrorScreen` is the router's `errorElement` (`routes.tsx`), reached
 *    via `useRouteError()` — a route that threw before any portal chrome
 *    mounted, so it renders `FullPageState` in `frame="standalone"`.
 *  - `PortalErrorFallback` is a portal layout's `ErrorBoundary` `fallback`
 *    (`portals/*\/index.tsx`) — a screen that threw *inside* an already-
 *    mounted portal, so it renders `frame="portal"` and never touches
 *    `useRouteError` (the boundary hands it the error directly).
 *
 * Neither exists to report by itself alone. `ErrorBoundary.componentDidCatch`
 * already calls `reportClientError` unconditionally before it ever renders a
 * fallback, so `PortalErrorFallback` must not double-report. `RouteErrorScreen`
 * has no boundary above it doing that — an error thrown before any component
 * caught it, or a real 404, reaches only this component — so it is the one
 * that reports, and only for a genuine failure: a 404 (or no error at all) is
 * not a bug to log.
 */

/** `true` only for a thrown `Response` carrying a real 404 — the shape
 * `classifyRouteError`'s injected `isNotFoundResponse` needs, and the same
 * check used to gate reporting below. */
function isNotFound404(error: unknown): boolean {
  return isRouteErrorResponse(error) && error.status === 404
}

/** Variants whose copy offers a `retry` action, so the caller must supply
 * `onRetry` for it to render at all (`FullPageStateBody` omits a retry
 * button with no handler rather than render a dead one). */
const RETRIABLE_VARIANTS = new Set(["offline", "service-trouble", "too-many-requests"])

function reload(): void {
  window.location.reload()
}

/**
 * Report a route-level failure exactly once per distinct `error`, skipping a
 * real 404 (or the absence of one) — see the module doc above for why this
 * component reports at all and `PortalErrorFallback` does not.
 */
function useReportRouteError(error: unknown): void {
  useEffect(() => {
    if (error === undefined || error === null) return
    if (isNotFound404(error)) return
    reportClientError({ error, kind: "render" })
    // `error` is the one dependency that matters: this must fire once per
    // distinct thrown value, not once per render of this screen (a 429's
    // live countdown re-renders this component every second).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error])
}

/** `service-trouble` alone needs the health poll (`useServiceHealth` fires a
 * `fetch` every 15s while mounted) — pulled into its own component, rather
 * than called unconditionally in the parent and conditionally rendered, so
 * that poll only ever runs while a reader is actually looking at this
 * variant. Calling the hook conditionally inside one component would break
 * the rules of hooks; mounting a different component conditionally does not. */
function ServiceTroubleState({
  frame,
  onRetry,
}: {
  frame: "standalone" | "portal"
  onRetry?: () => void
}) {
  const health = useServiceHealth()
  return <FullPageState variant="service-trouble" frame={frame} onRetry={onRetry} health={health} />
}

/** Shared by both exports below: turn a `RouteFailure` plus the two live
 * extras into the actual `FullPageState` render, including the "a reload is
 * already under way" case. */
function renderFailure(
  failure: RouteFailure,
  frame: "standalone" | "portal",
  onRetry: (() => void) | undefined,
  retryAfterSeconds: number,
) {
  if (failure.reloading) {
    // The tab is about to hard-reload out from under whatever renders here —
    // "render nothing but paper" per the approved canvas, not a screen with
    // copy the reader has no time to read. In the portal frame there is no
    // honest "paper" of its own to paint (the portal's own chrome already
    // is), so this renders nothing at all rather than a mismatched full-page
    // block sitting inside the content slot.
    return frame === "standalone" ? <div className="min-h-screen bg-paper" /> : null
  }

  if (failure.variant === "service-trouble") {
    return <ServiceTroubleState frame={frame} onRetry={onRetry} />
  }

  return (
    <FullPageState
      variant={failure.variant}
      frame={frame}
      onRetry={onRetry}
      retryAfterSeconds={failure.variant === "too-many-requests" ? retryAfterSeconds : undefined}
    />
  )
}

/** The router's top-level `errorElement` (`routes.tsx`). */
export function RouteErrorScreen() {
  const error = useRouteError()
  const online = useOnlineStatus()

  useReportRouteError(error)

  const failure = classifyRouteError(error, {
    online,
    attemptReload: handleChunkError,
    isNotFoundResponse: isNotFound404,
  })

  // Called unconditionally regardless of `failure.variant` — rules of hooks —
  // and simply not read unless the variant is `too-many-requests`. Reseeded
  // from `failure.retryAfterSeconds` on every render, which only actually
  // changes across renders when a fresh error replaces this one.
  const countdown = useCountdown(failure.retryAfterSeconds ?? 0)

  const onRetry = RETRIABLE_VARIANTS.has(failure.variant) ? reload : undefined

  return renderFailure(failure, "standalone", onRetry, countdown)
}

/**
 * A portal layout's `ErrorBoundary` `fallback` (`portals/*\/index.tsx`), for
 * a render error caught *inside* an already-mounted portal rather than one
 * that stopped a route from ever rendering at all.
 *
 * `reset` is `ErrorBoundary.reset` — it clears the caught error and lets
 * React try `children` again, which is a strictly better recovery than a full
 * page reload for a portal whose sidebar and header are still fine: the
 * reader keeps their place in the app. Wired as `onRetry` for the three
 * variants the copy table gives a retry action, and for `crash` as well —
 * see `FullPageState.tsx`'s own note on why `crash` gets a `reset`-backed
 * "Try again" here that a route-level crash does not.
 */
export function PortalErrorFallback({ error, reset }: { error: Error; reset: () => void }) {
  const online = useOnlineStatus()

  const failure = classifyRouteError(error, {
    online,
    attemptReload: handleChunkError,
    isNotFoundResponse: isNotFound404,
  })

  const countdown = useCountdown(failure.retryAfterSeconds ?? 0)

  const onRetry =
    RETRIABLE_VARIANTS.has(failure.variant) || failure.variant === "crash" ? reset : undefined

  return renderFailure(failure, "portal", onRetry, countdown)
}

/**
 * `ErrorBoundary`'s `fallback` prop for the four portal layouts
 * (`portals/*\/index.tsx`), as a plain, stable function reference rather than
 * an arrow closure written inline at each of the four call sites. Behaviourally
 * identical either way — `ErrorBoundary` just calls whatever `fallback` it was
 * given with `(error, reset)` — this exists so the four portals share one
 * definition instead of four character-for-character copies of the same line.
 */
export function portalErrorFallback(error: Error, reset: () => void) {
  return <PortalErrorFallback error={error} reset={reset} />
}

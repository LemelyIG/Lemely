/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useState } from "react"
import { isRouteErrorResponse, useLocation, useRouteError } from "react-router-dom"
import { FullPageState } from "@/portals/misc/FullPageState"
import { classifyRouteError, type RouteFailure } from "@/lib/routeError"
import { useOnlineStatus } from "@/lib/online"
import { canReloadChunkError, handleChunkError, isChunkLoadError } from "@/lib/staleChunk"
import { reportClientError } from "@/lib/clientErrors"
import { useCountdown } from "@/lib/hooks/useCountdown"
import { useServiceHealth } from "@/lib/hooks/useServiceHealth"
import { safeNextPath } from "@/lib/nextPath"

/*
 * PR 2 part A2 · which full-page state a route-level failure renders, wired
 * to the real browser.
 *
 * `classifyRouteError` (`lib/routeError.ts`) is the pure decision; everything
 * here is the plumbing that decision needs to run for real: `useRouteError`
 * for the thrown value, `useOnlineStatus` for connectivity, `canReloadChunkError`
 * as the (also pure) "would a reload happen" predicate classification reads,
 * and `useCountdown`/`useServiceHealth` for the two variants that keep
 * changing after the first render.
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
 * that reports, and only for a genuine failure: a 404 (or no error at all),
 * and a stale-chunk failure (see `useReportRouteError` below), are not bugs
 * to log.
 *
 * **Classification stays pure; the reload does not.** `classifyRouteError`
 * is called from the render body, same as before, but it now only ever asks
 * `canReloadChunkError` — a plain storage read with no write and no
 * `location.reload()` — so calling it twice for the same error is guaranteed
 * to answer the same way, including under `<StrictMode>`'s intentional
 * double-render and a discarded render under concurrent rendering. The real
 * reload (`handleChunkError`, which does write storage and does navigate) is
 * attempted from `useReloadInProgress`'s `useEffect` below, which only ever
 * runs for a render that actually committed.
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
 * `onRetry` for the standalone frame (`RouteErrorScreen`). Mirrors
 * `RETRIABLE_VARIANTS` for every variant except `offline`: a hard
 * `location.reload()` while genuinely offline tears down this designed
 * screen and hands the tab to the browser's own network-error page instead —
 * a strictly worse outcome than doing nothing. Unlike `PortalErrorFallback`
 * below, the standalone frame has no `reset()` to re-render in place with
 * either — it is the router's `errorElement`, not an `ErrorBoundary` — so
 * the honest choice here is to omit the action and let `useOnlineStatus` do
 * the recovering: the instant the browser reports `online`, this component
 * re-renders and `classifyRouteError` reclassifies away from `offline` on
 * its own, with no button needed.
 */
function standaloneOnRetry(variant: RouteFailure["variant"]): (() => void) | undefined {
  if (variant === "offline") return undefined
  return RETRIABLE_VARIANTS.has(variant) ? reload : undefined
}

/**
 * Report a route-level failure exactly once per distinct `error`, skipping a
 * real 404 (or the absence of one) and a stale-chunk failure — see the
 * module doc above for why this component reports at all and
 * `PortalErrorFallback` does not.
 *
 * A stale-chunk failure is skipped unconditionally, not only while a reload
 * is under way: it is an expected side effect of a deploy landing under an
 * open tab, not a code defect, and it is already self-healing either way
 * (the guard reloads it away, or the tab falls through to the "reload
 * needed" screen with a working button of its own). Reporting it would cost
 * one `POST /api/client-errors` per open tab per deploy for a category of
 * failure nobody needs paged for.
 */
function useReportRouteError(error: unknown): void {
  useEffect(() => {
    if (error === undefined || error === null) return
    if (isNotFound404(error)) return
    if (isChunkLoadError(error)) return
    reportClientError({ error, kind: "render" })
    // `error` is the one dependency that matters: this must fire once per
    // distinct thrown value, not once per render of this screen (a 429's
    // live countdown re-renders this component every second).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error])
}

/** How long to give a guarded reload to actually navigate away before
 * falling through to the ordinary "reload needed" screen and its own working
 * button — SHOULD-FIX 6's escape hatch for a `location.reload()` a
 * `beforeunload` handler blocks, or a suspended background tab defers
 * indefinitely. Chosen generously above real reload latency (which is
 * effectively instant once triggered) without being so long a genuinely
 * stuck reader sits on bare paper for a noticeable stretch. */
const RELOAD_ESCAPE_HATCH_MS = 2000

/**
 * The one place this module performs the actual, side-effecting reload
 * `classifyRouteError` decided was warranted (`failure.reloading`) — from a
 * `useEffect`, deliberately never from the render body that produced
 * `failure` (see the module doc above for why that matters under
 * `<StrictMode>` and concurrent rendering).
 *
 * Also owns the SHOULD-FIX 6 escape hatch: if `location.reload()` never
 * actually navigates away within `RELOAD_ESCAPE_HATCH_MS`, `stuck` flips to
 * `true` and this returns `false`, so the caller falls through to the
 * ordinary "reload needed" screen (with its own working reload button)
 * instead of leaving the reader on bare paper forever. The timer is cleared
 * on unmount and reset for every new `error`/`reloading` pair.
 *
 * Returns whether the caller should still render the reloading (paper-only)
 * state right now.
 */
function useReloadInProgress(failure: RouteFailure, error: unknown): boolean {
  const [stuck, setStuck] = useState(false)

  useEffect(() => {
    setStuck(false)
    if (!failure.reloading) return undefined

    handleChunkError(error)

    const timer = window.setTimeout(() => setStuck(true), RELOAD_ESCAPE_HATCH_MS)
    return () => window.clearTimeout(timer)
    // `error` and `failure.reloading` are the two things that matter: a
    // fresh error (or a fresh classification landing on `reloading` again)
    // is a fresh reload attempt to time-box, nothing else here should
    // restart it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error, failure.reloading])

  return failure.reloading === true && !stuck
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

/** Shared by both exports below: turn a `RouteFailure` plus the live extras
 * into the actual `FullPageState` render, including the "a reload is already
 * under way" case. `reloading` is passed in rather than read off `failure`
 * directly — it is `useReloadInProgress`'s own (escape-hatch-aware) answer,
 * which can fall back to `false` after `failure.reloading` stays `true`. */
function renderFailure(
  failure: RouteFailure,
  frame: "standalone" | "portal",
  onRetry: (() => void) | undefined,
  retryAfterSeconds: number,
  reloading: boolean,
  returnTo: string | undefined,
) {
  if (reloading) {
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
      returnTo={returnTo}
    />
  )
}

/** The router's top-level `errorElement` (`routes.tsx`). */
export function RouteErrorScreen() {
  const error = useRouteError()
  const online = useOnlineStatus()
  const location = useLocation()

  useReportRouteError(error)

  const failure = classifyRouteError(error, {
    online,
    canReload: canReloadChunkError,
    isNotFoundResponse: isNotFound404,
  })

  const reloading = useReloadInProgress(failure, error)

  // Called unconditionally regardless of `failure.variant` — rules of hooks —
  // and simply not read unless the variant is `too-many-requests`. Reseeded
  // from `failure.retryAfterSeconds` on every render, which only actually
  // changes across renders when a fresh error replaces this one.
  const countdown = useCountdown(failure.retryAfterSeconds ?? 0)

  const onRetry = standaloneOnRetry(failure.variant)

  // Re-validated the same way `SessionEnded.tsx` re-validates its own
  // `?next=`: this is the current address the browser bar shows, which is
  // exactly as untrusted as a query param once it reaches a component (a
  // reader can be here via a crafted link, not only the app's own
  // navigation), so it goes through the same same-origin-path allowlist
  // before `FullPageState`'s `sign-in` action ever carries it on to
  // `/login?next=…`. Only meaningful for `session-ended`; every other
  // variant's copy simply never reads `returnTo`.
  const returnTo = safeNextPath(`${location.pathname}${location.search}`) ?? undefined

  return renderFailure(failure, "standalone", onRetry, countdown, reloading, returnTo)
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
 * variants the copy table gives a retry action (including `offline`, where
 * re-rendering in place is the honest choice a full reload is not — see
 * `standaloneOnRetry` above for the frame that lacks this option), and for
 * `crash` as well — see `FullPageState.tsx`'s own note on why `crash` gets a
 * `reset`-backed "Try again" here that a route-level crash does not.
 */
export function PortalErrorFallback({ error, reset }: { error: Error; reset: () => void }) {
  const online = useOnlineStatus()
  const location = useLocation()

  const failure = classifyRouteError(error, {
    online,
    canReload: canReloadChunkError,
    isNotFoundResponse: isNotFound404,
  })

  const reloading = useReloadInProgress(failure, error)

  const countdown = useCountdown(failure.retryAfterSeconds ?? 0)

  const onRetry =
    RETRIABLE_VARIANTS.has(failure.variant) || failure.variant === "crash" ? reset : undefined

  const returnTo = safeNextPath(`${location.pathname}${location.search}`) ?? undefined

  return renderFailure(failure, "portal", onRetry, countdown, reloading, returnTo)
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

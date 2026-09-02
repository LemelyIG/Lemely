import { useEffect, useState } from "react"

/*
 * PR 2 part A2 · the live "try again in m:ss" countdown `too-many-requests`
 * shows.
 *
 * `FullPageStateBody` (`portals/misc/FullPageState.tsx`) is explicit that it
 * "never starts a timer or polls anything itself" — the caller owns that and
 * re-renders with a fresh prop. This hook is that caller-side timer:
 * `RouteErrorScreen`/`PortalErrorFallback` seed it with the seconds a 429
 * carried (or the 30s default `routeError.ts` falls back to) and pass the
 * ticking value straight through as `retryAfterSeconds`.
 */

/**
 * Count down from `initialSeconds` to `0`, ticking once per second, and
 * return the seconds remaining.
 *
 * Resets to `initialSeconds` whenever it changes — a caller re-rendering this
 * with a new value is starting a new retry window (a different 429, a fresh
 * mount on a different route after react-router's `errorElement` remounts),
 * and the countdown should reflect that window, not keep ticking down the
 * one before it.
 */
export function useCountdown(initialSeconds: number): number {
  const [remaining, setRemaining] = useState(initialSeconds)

  useEffect(() => {
    setRemaining(initialSeconds)
  }, [initialSeconds])

  useEffect(() => {
    if (remaining <= 0) return
    const timer = window.setTimeout(() => {
      setRemaining((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => window.clearTimeout(timer)
  }, [remaining])

  return remaining
}

import { useEffect, useState } from "react"

/*
 * PR 2 part A2 · the live status row `service-trouble` shows.
 *
 * `GET /api/health` (`lemely/web/routers/meta.py`) is a public endpoint — no
 * bearer token, no auth guard — polled here on plain `fetch`, deliberately
 * not through `request()` in `@/lib/api`: that client throws `ApiError` on
 * any non-2xx response, and a 5xx from the health check itself is exactly the
 * outcome this hook exists to report to a screen that is *already* showing
 * "service trouble" for a different reason. Throwing here would take the one
 * screen meant to survive the backend being down down with it.
 */

export type ServiceHealthStatus = "unknown" | "responding" | "not-responding"

export interface ServiceHealth {
  status: ServiceHealthStatus
  /** Seconds since the last completed check, or `null` before the first one
   * has resolved. */
  checkedSecondsAgo: number | null
}

const POLL_INTERVAL_MS = 15_000
const AGE_TICK_MS = 1_000

/**
 * Map a completed check's outcome to the three-way status `FullPageState`
 * renders. `ok === null` means no check has completed yet — genuinely
 * different from "checked and it failed", which is why this is three states
 * and not a boolean. Exported so `tests/unit/serviceHealth.test.ts` can pin
 * the mapping without mocking `fetch` or a timer.
 */
export function healthFromResponse(ok: boolean | null): ServiceHealthStatus {
  if (ok === null) return "unknown"
  return ok ? "responding" : "not-responding"
}

/**
 * Poll `GET /api/health` every 15s for as long as this hook stays mounted,
 * and report whether it is answering.
 *
 * `RouteErrorScreen`/`PortalErrorFallback` render this only for the
 * `service-trouble` variant (see those callers), so the poll only ever runs
 * while a reader is actually looking at that screen — nothing here throttles
 * it further on its own.
 */
export function useServiceHealth(): ServiceHealth {
  const [ok, setOk] = useState<boolean | null>(null)
  const [checkedAt, setCheckedAt] = useState<number | null>(null)
  const [now, setNow] = useState<number>(() => Date.now())

  useEffect(() => {
    let cancelled = false

    const check = (): void => {
      fetch("/api/health")
        .then((res) => {
          if (cancelled) return
          setOk(res.ok)
          setCheckedAt(Date.now())
        })
        .catch(() => {
          if (cancelled) return
          setOk(false)
          setCheckedAt(Date.now())
        })
    }

    check()
    const poll = window.setInterval(check, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(poll)
    }
  }, [])

  // A second, independent interval for the "checked N s ago" line, so it
  // keeps counting up between polls instead of jumping in 15s steps.
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), AGE_TICK_MS)
    return () => window.clearInterval(tick)
  }, [])

  const checkedSecondsAgo =
    checkedAt === null ? null : Math.max(0, Math.round((now - checkedAt) / 1000))

  return { status: healthFromResponse(ok), checkedSecondsAgo }
}

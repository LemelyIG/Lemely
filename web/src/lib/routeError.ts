import { ApiError } from "@/lib/api"
import { isChunkLoadError } from "@/lib/staleChunk"
import type { FullPageStateVariant } from "@/portals/misc/fullPageStateCopy"

/*
 * PR 2 part A2 · which full-page state a route-level failure shows.
 *
 * Pure and React-router-free on purpose, same reasoning as `staleChunk.ts` and
 * `online.ts`: `classifyRouteError` is the decision `RouteErrorScreen`
 * (`components/route-error.tsx`) and `PortalErrorFallback` both delegate to,
 * and a decision this load-bearing needs a test that can pin every row of the
 * table under plain Node, with no router context and no DOM to construct one.
 *
 * `isRouteErrorResponse` is deliberately not imported here — it is a
 * react-router function, and importing it would tie this module to a router
 * context this file has no other reason to need. The caller injects the one
 * fact this module actually wants from it (`isNotFoundResponse`) instead, so
 * a test can hand this function a plain object shaped like a `Response`
 * error rather than a real router error boundary.
 *
 * `canReload` is `canReloadChunkError` in production, injected for the same
 * reason: it reaches into `staleChunk.ts`'s module-level `installed` state,
 * and a unit test needs to observe "would a reload be attempted" as a plain
 * boolean return. It is deliberately the *pure* predicate
 * (`StaleChunkGuard.canReload`, a storage read) rather than `handleChunkError`
 * (a storage write plus a real `location.reload()`): this function runs in a
 * render body, so calling it must never itself be the reload — the caller
 * (`RouteErrorScreen`/`PortalErrorFallback` in `components/route-error.tsx`)
 * performs the actual `handleChunkError` call from a `useEffect` keyed on the
 * error, once classification has already decided a reload is warranted. Two
 * calls to `classifyRouteError` with the same `error` are guaranteed to
 * return the same `RouteFailure` as a result — see `routeError.test.ts`'s
 * purity assertions.
 */

/** The outcome of classifying a route-level failure: which `FullPageState`
 * variant to show, and the two variant-specific extras a caller may need to
 * wire up. */
export interface RouteFailure {
  variant: FullPageStateVariant
  /** Set only for `"too-many-requests"` — the seconds to count down from,
   * either the server's own `Retry-After` or the 30s default when it sent
   * none. */
  retryAfterSeconds?: number
  /**
   * The guard would reload for this build right now (`canReload` returned
   * `true`) — the caller should attempt the real reload (from a
   * `useEffect`, never from render) and render nothing but paper while it
   * does, since the tab is about to reload out from under whatever it
   * paints and there is no honest "new version" copy to show for the
   * instant before that happens. Purely a classification of *intent*: this
   * flag does not mean a reload has happened, or even been attempted yet —
   * `classifyRouteError` never attempts one itself (see the module doc
   * above).
   */
  reloading?: boolean
}

/** A 429 with no `Retry-After` header at all still needs a number to count
 * down from; this is the approved canvas's fallback. */
const DEFAULT_RETRY_AFTER_SECONDS = 30

/**
 * Decide which of the nine `FullPageState` variants a caught route error (or
 * its absence) should show.
 *
 * The table, in the order it is checked:
 *  - no error, or a thrown 404 `Response` → `not-found`.
 *  - a chunk-load failure (`isChunkLoadError`) while offline → `offline`
 *    (there is no point reloading a tab that cannot reach the CDN at all);
 *    online, with a reload already under way → `reloading: true`; online,
 *    with no reload attempted (the guard already spent its one reload on
 *    this build) → `new-version`.
 *  - an `ApiError`: 401 → `session-ended`; 403 → `no-access`; 429 →
 *    `too-many-requests` with a live countdown; status 0 (no response
 *    reached the server at all) → `offline` when the browser itself is
 *    offline, else `service-trouble`; ≥ 500 → `service-trouble`.
 *  - anything else → `crash`.
 */
export function classifyRouteError(
  error: unknown,
  ctx: {
    online: boolean
    canReload: (error: unknown) => boolean
    isNotFoundResponse: (error: unknown) => boolean
  },
): RouteFailure {
  if (error === undefined || error === null || ctx.isNotFoundResponse(error)) {
    return { variant: "not-found" }
  }

  if (isChunkLoadError(error)) {
    if (!ctx.online) return { variant: "offline" }
    if (ctx.canReload(error)) return { variant: "new-version", reloading: true }
    return { variant: "new-version" }
  }

  if (error instanceof ApiError) {
    if (error.status === 401) return { variant: "session-ended" }
    if (error.status === 403) return { variant: "no-access" }
    if (error.status === 429) {
      return {
        variant: "too-many-requests",
        retryAfterSeconds: error.retryAfter ?? DEFAULT_RETRY_AFTER_SECONDS,
      }
    }
    if (error.status === 0) {
      return { variant: ctx.online ? "service-trouble" : "offline" }
    }
    if (error.status >= 500) return { variant: "service-trouble" }
  }

  return { variant: "crash" }
}

/** Does `trimmed` look like the delta-seconds form (`Retry-After: 120`),
 * rather than an HTTP-date (`Retry-After: Wed, 21 Oct ...`)? Both are legal
 * per RFC 9110 §10.2.3; this is the cheapest way to tell them apart before
 * trying to parse either. */
function isDeltaSeconds(trimmed: string): boolean {
  return /^\d+$/.test(trimmed)
}

/**
 * True for a string that *looks* like a delta-seconds value but failed
 * `isDeltaSeconds` because of a sign or a decimal point (`"-5"`, `"+30"`,
 * `"5.5"`) — RFC 9110's delta-seconds form is unsigned digits only, so none
 * of these are ever a legal `Retry-After`. They must be rejected here,
 * before ever reaching `new Date()`: V8's legacy (non-ISO) date parser
 * accepts several of them as some other, unrelated date — `new Date("-5")`
 * is "Tue May 01 2001" and `new Date("5.5")` is "Sat May 05 2001" on this
 * engine, neither of which is `Invalid Date`, so without this check they
 * would silently produce a real (bogus) countdown instead of the `null`
 * "no usable information" this function should return for them.
 */
function looksLikeMalformedDelta(trimmed: string): boolean {
  return /^[+-]\d+$|^[+-]?\d+\.\d+$/.test(trimmed)
}

/**
 * Upper bound on the seconds this function ever returns. `Retry-After` is
 * meant to be a short, human-scale wait — RFC 9110 gives no ceiling, so a
 * malicious or malformed value (`Retry-After: 99999999999999999999`) would
 * otherwise disable the 429 screen's only action (and `useCountdown`'s
 * timer) for effectively forever. An hour is generous enough for any real
 * rate-limit response this app's backend sends, and short enough that a
 * reader is never trapped on a dead retry button.
 */
const MAX_RETRY_AFTER_SECONDS = 3600

/**
 * Parse a `Retry-After` header value into a whole number of seconds to wait,
 * measured from `now`.
 *
 * Accepts either form the header can take: a delta in seconds, or an
 * HTTP-date to count down to. Returns `null` for a missing or unparseable
 * header — a caller with nothing better falls back to its own default (see
 * `DEFAULT_RETRY_AFTER_SECONDS` above) rather than this function inventing
 * one, since only the caller knows what "no information" should mean for it.
 *
 * Clamped to `[0, MAX_RETRY_AFTER_SECONDS]`: never negative (a date in the
 * past — clock skew, or a server naming a moment that has already arrived —
 * clamps to `0` rather than counting up), and never above the ceiling above.
 */
export function parseRetryAfter(header: string | null, now: Date): number | null {
  if (header === null) return null
  const trimmed = header.trim()
  if (trimmed === "") return null

  if (isDeltaSeconds(trimmed)) {
    const seconds = Number(trimmed)
    if (!Number.isFinite(seconds)) return null
    return Math.min(MAX_RETRY_AFTER_SECONDS, Math.max(0, Math.round(seconds)))
  }

  if (looksLikeMalformedDelta(trimmed)) return null

  const target = new Date(trimmed)
  const targetMs = target.getTime()
  if (Number.isNaN(targetMs)) return null

  const deltaSeconds = Math.round((targetMs - now.getTime()) / 1000)
  return Math.min(MAX_RETRY_AFTER_SECONDS, Math.max(0, deltaSeconds))
}

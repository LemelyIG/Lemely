/*
 * PR 1 part B · client-side error reporting.
 *
 * `ErrorBoundary` (componentDidCatch), `main.tsx` (window "error" /
 * "unhandledrejection") and the lazy-chart wrapper all funnel into
 * `reportClientError` below, which is the one place that knows how to turn
 * an arbitrary caught value into `POST /api/client-errors`. Everything that
 * can be tested without a DOM is split out as a pure function: the report
 * shape (`buildClientErrorReport`) and the rate limiter (`ReportThrottle`)
 * take their inputs as arguments rather than reading `window`/`Date.now()`
 * themselves, so `tests/unit/clientErrors.test.ts` can pin both under plain
 * Node with no mocked globals.
 *
 * Deliberately NOT built on `request()` from `@/lib/api`. That client throws
 * `ApiError` on a non-2xx response and on a network failure, and the one
 * property this path cannot have is a way to throw: an error thrown while
 * reporting an error is exactly how a crash loop starts (an `ErrorBoundary`
 * whose own logging call throws would fail `componentDidCatch` itself,
 * which React re-throws past the boundary). So this module talks to
 * `fetch` directly and swallows every outcome — a 202, a 429, a 422, a
 * network failure, all look identical to the caller: nothing happens.
 */

/** Mirrors the backend's three-way discriminant on `POST /api/client-errors`
 * (agent C, this PR). `render` is a caught `componentDidCatch`; `unhandled`
 * is `window.onerror`; `rejection` is an unhandled promise rejection. */
export type ClientErrorKind = "render" | "unhandled" | "rejection"

/** The exact camelCase body `POST /api/client-errors` accepts. Field limits
 * are enforced by `buildClientErrorReport` below, not by the server alone —
 * truncating client-side keeps an oversized stack from being rejected
 * outright (a 422 here has nowhere to surface: this path never retries or
 * reports its own failure) and keeps the request small on a slow
 * connection. */
export interface ClientErrorReport {
  message: string
  stack: string | null
  componentStack: string | null
  route: string
  buildId: string
  kind: ClientErrorKind
  userAgent: string | null
  occurredAt: string
}

const MESSAGE_LIMIT = 2000
const STACK_LIMIT = 8000
const ROUTE_LIMIT = 500
const BUILD_ID_LIMIT = 64
const USER_AGENT_LIMIT = 500

/** Query keys that plausibly carry a bearer credential. Redacted, not
 * stripped: keeping the key and blanking the value tells the reader of a
 * Cloud Logging entry that a token *was* present without shipping the token
 * itself into the log. Matched case-sensitively against the literal
 * `access_token` / `refresh_token` spellings plus the bare `token` and
 * `code` params real flows in this app use (`/reset/:token`,
 * `/login?code=...`-style OAuth-ish redirects). */
const SENSITIVE_QUERY_KEYS = new Set(["token", "code", "access_token", "refresh_token"])

/**
 * Cut `value` to at most `limit` UTF-16 code units, never leaving a lone
 * high surrogate at the end.
 *
 * `String#slice` counts UTF-16 code units, and an astral character (most
 * emoji, several scripts) is two of them — a surrogate *pair*. A limit that
 * lands the cut between the two halves keeps the leading (high) surrogate
 * with no low surrogate to follow it. That string round-trips through
 * `JSON.stringify`/`JSON.parse` — JSON only requires valid UTF-16, and a
 * lone surrogate is legal UTF-16 — so it reaches the backend, but Python's
 * `sys.stdout`/`stderr` (structlog's own output, per the contract this
 * report travels under) encode as UTF-8 by default, which a lone surrogate
 * cannot represent, so a write of one such log line raises there instead.
 * Cheaper to never produce it here than to trust every consumer downstream
 * to expect it.
 */
function truncate(value: string, limit: number): string {
  if (value.length <= limit) return value
  const cut = value.slice(0, limit)
  const lastUnit = cut.charCodeAt(cut.length - 1)
  const endsInHighSurrogate = lastUnit >= 0xd800 && lastUnit <= 0xdbff
  return endsInHighSurrogate ? cut.slice(0, -1) : cut
}

/**
 * Strip anything in the query string that looks like a credential, keeping
 * the path and the rest of the query untouched.
 *
 * Takes `pathname + search` (never a full URL, and never the hash — a hash
 * can carry an implicit-grant access token directly, e.g.
 * `#access_token=...` from an OAuth redirect, and the fragment never leaves
 * the browser in a normal request, so the caller is responsible for not
 * passing one in here at all rather than this function trying to launder
 * it out).
 *
 * A malformed query string (one `URLSearchParams` cannot make sense of) is
 * left as-is rather than thrown away: reporting a slightly-less-redacted
 * route beats reporting no route, and `URLSearchParams` in practice never
 * throws — it degrades unparseable pairs to empty values instead — so this
 * is a defensive fallback, not a path this module expects to take.
 */
export function redactRoute(route: string): string {
  const queryStart = route.indexOf("?")
  if (queryStart === -1) return route
  const path = route.slice(0, queryStart)
  const query = route.slice(queryStart + 1)
  try {
    const params = new URLSearchParams(query)
    let redacted = false
    for (const key of params.keys()) {
      if (SENSITIVE_QUERY_KEYS.has(key)) {
        params.set(key, "redacted")
        redacted = true
      }
    }
    return redacted ? `${path}?${params.toString()}` : route
  } catch {
    return route
  }
}

/** Extract a message + stack from anything a `catch`, `componentDidCatch` or
 * `window.onerror` can hand us. Non-`Error` throwables (a string, a plain
 * object, `undefined`) are real and reachable — `throw "oops"` is valid JS —
 * and `String(x)` is the same fallback `ApiError`'s own catch-all uses in
 * `lib/api.ts`, so a caught non-Error reads the same way here as it does
 * everywhere else in this client. Such a value never has a stack. */
function describeThrown(error: unknown): { message: string; stack: string | null } {
  if (error instanceof Error) {
    return { message: error.message, stack: error.stack ?? null }
  }
  return { message: String(error), stack: null }
}

/**
 * Build the exact wire body for `POST /api/client-errors` from a caught
 * value plus the call site's context. Pure and synchronous — no `fetch`, no
 * `window` — so every truncation/redaction rule is unit-testable without a
 * DOM (`tests/unit/clientErrors.test.ts`).
 *
 * Never reads `localStorage`/`sessionStorage`: the report exists to reach a
 * log a support engineer can read, and a session's stored auth/profile data
 * has no business landing there. `route`, `userAgent` and `now` are passed
 * in rather than read from the ambient `window`/`navigator`/`Date` for the
 * same testability reason as the clock in `ReportThrottle` below.
 */
export function buildClientErrorReport(input: {
  error: unknown
  kind: ClientErrorKind
  componentStack?: string | null
  route: string
  buildId: string
  userAgent: string | null
  now: Date
}): ClientErrorReport {
  const { message, stack } = describeThrown(input.error)
  return {
    message: truncate(message, MESSAGE_LIMIT),
    stack: stack === null ? null : truncate(stack, STACK_LIMIT),
    componentStack:
      input.componentStack == null ? null : truncate(input.componentStack, STACK_LIMIT),
    route: truncate(redactRoute(input.route), ROUTE_LIMIT),
    buildId: truncate(input.buildId, BUILD_ID_LIMIT),
    kind: input.kind,
    userAgent: input.userAgent === null ? null : truncate(input.userAgent, USER_AGENT_LIMIT),
    occurredAt: input.now.toISOString(),
  }
}

const MAX_REPORTS_PER_WINDOW = 5
const RATE_WINDOW_MS = 60_000
const DUPLICATE_WINDOW_MS = 5 * 60_000

/**
 * Client-side rate limiting for error reports, so a component stuck in a
 * render-throw-catch-render loop cannot turn itself into a request flood.
 * The backend has its own limiter (429, per the contract), but this one
 * exists to stop the *browser tab* from hammering `keepalive: true`
 * requests at all — the server-side 429 still costs a round trip per
 * attempt, and `keepalive` requests are explicitly exempted from a page's
 * normal request cancellation, so a loop here would keep firing even as the
 * user navigates away.
 *
 * Two independent rules, both enforced by `shouldReport`:
 *  - at most `MAX_REPORTS_PER_WINDOW` reports in any trailing
 *    `RATE_WINDOW_MS` (a sliding window, not a fixed bucket — the oldest
 *    timestamp is dropped only once it falls outside the window relative to
 *    *now*, not relative to when the window "started").
 *  - an exact duplicate (same message + stack + route) is dropped if one was
 *    already reported within the last `DUPLICATE_WINDOW_MS`, so a single
 *    persistently-broken widget that re-throws on every re-render doesn't
 *    spend the whole rate budget on one already-known failure.
 *
 * The clock is injected (`clock: () => number`, defaulting to `Date.now`)
 * rather than read globally so `tests/unit/clientErrors.test.ts` can drive
 * it with a fake one instead of faking timers.
 */
export class ReportThrottle {
  private readonly clock: () => number
  private recentTimestamps: number[] = []
  private readonly recentDuplicates = new Map<string, number>()

  constructor(clock: () => number = Date.now) {
    this.clock = clock
  }

  /** Same identity `buildClientErrorReport` sends, collapsed to one string —
   * two reports are "the same" report for throttling purposes exactly when
   * these three fields agree. */
  private static keyOf(report: Pick<ClientErrorReport, "message" | "stack" | "route">): string {
    return `${report.route} ${report.message} ${report.stack ?? ""}`
  }

  /**
   * Decide whether `report` should go out, and record it as sent if so.
   *
   * A single check-and-record method (rather than a separate `record()`) is
   * deliberate: the two rules above only make sense evaluated against the
   * same "now", and a caller that checked then separately recorded could
   * race a burst of synchronous throws into checking against a window that
   * hadn't yet accounted for the one before it.
   */
  shouldReport(report: Pick<ClientErrorReport, "message" | "stack" | "route">): boolean {
    const now = this.clock()

    this.recentTimestamps = this.recentTimestamps.filter((t) => now - t < RATE_WINDOW_MS)
    for (const [key, seenAt] of this.recentDuplicates) {
      if (now - seenAt >= DUPLICATE_WINDOW_MS) this.recentDuplicates.delete(key)
    }

    const key = ReportThrottle.keyOf(report)
    if (this.recentDuplicates.has(key)) return false
    if (this.recentTimestamps.length >= MAX_REPORTS_PER_WINDOW) return false

    this.recentTimestamps.push(now)
    this.recentDuplicates.set(key, now)
    return true
  }
}

/** Shared by every call site in this tab, so "5 per minute" is a budget for
 * the whole page, not 5 per boundary — a screen with three independently
 * crashing widgets should not get 15 requests out just because each has its
 * own `ErrorBoundary`. */
const throttle = new ReportThrottle()

/**
 * Vite replaces this identifier at build time (`vite.config.ts`'s `define`)
 * with the short commit SHA `deploy.yml` builds from, or `"dev"` locally.
 * `src/vite-env.d.ts` declares its type (`string`) for both `tsc -b`
 * projects that check this file (see that config's own `include` comment).
 * The `typeof` guard stays regardless of the type: `vitest.config.ts` is a
 * separate config that never runs Vite's `define` substitution, so under
 * the unit-test runner the identifier is real at the type level but does
 * not exist at runtime, and a bare reference would throw a `ReferenceError`
 * before a single assertion ran.
 */
function currentBuildId(): string {
  return typeof __LEMELY_BUILD_ID__ === "string" ? __LEMELY_BUILD_ID__ : "dev"
}

/**
 * Fire a client error report and forget it. The one function in this module
 * with side effects; everything it needs from the environment is gathered
 * here so `buildClientErrorReport` and `ReportThrottle` stay pure.
 *
 * Never throws and never rejects visibly: `fetch(...).catch(() => {})`
 * discards a network failure the same way a dropped 429/422 is discarded —
 * this path has no retry and no secondary place to report its own failure,
 * so the only safe behaviour is silence. `keepalive: true` lets the request
 * survive a navigation or tab close that happens in the same tick as an
 * unload-time error (e.g. an `unhandledrejection` firing as the reader
 * clicks away), which a normal `fetch` would otherwise abort.
 */
export function reportClientError(input: {
  error: unknown
  kind: ClientErrorKind
  componentStack?: string | null
}): void {
  if (import.meta.env.DEV) {
    // Never silenced in development: this is the one place a developer
    // would otherwise lose the original error entirely, since the whole
    // point of this module is to keep it from reaching the console as an
    // uncaught throw.
    console.error(input.error)
  }

  const report = buildClientErrorReport({
    error: input.error,
    kind: input.kind,
    componentStack: input.componentStack,
    route: `${window.location.pathname}${window.location.search}`,
    buildId: currentBuildId(),
    userAgent: typeof navigator === "undefined" ? null : navigator.userAgent,
    now: new Date(),
  })

  if (!throttle.shouldReport(report)) return

  fetch("/api/client-errors", {
    method: "POST",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(report),
  }).catch(() => {
    // Fire-and-forget, per the module doc above: a failed report is not
    // itself reportable.
  })
}

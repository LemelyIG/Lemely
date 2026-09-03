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
 * itself into the log. Matched case-insensitively (`?Token=` is exactly as
 * live a leak as `?token=`) against the literal `access_token` /
 * `refresh_token` spellings plus the bare `token` and `code` params real
 * flows in this app use (`/login?code=...`-style OAuth-ish redirects). The
 * credential-bearing routes this app actually mounts — `/reset/:token`,
 * `/verify-email/:token`, `/join/:code` — put the value in the *path*, not
 * the query, which is what the path-segment redaction below exists for.
 *
 * `next` (PR 2 · nit, adversarial review): `lib/nextPath.ts`'s `?next=`
 * carrier is itself a same-origin *path*, and that path can be
 * `/reset/<token>` or `/verify-email/<token>` — one of the very credentials
 * this set exists to keep out of a log. `RequireAuth`/`SessionEnded`/`Login`
 * all put a raw, unredacted path there, so a render crash on
 * `/login?next=/reset/<token>` would otherwise write a live password-reset
 * token to Cloud Logging through the query string instead of the path this
 * module already guards. Redacting it here loses nothing worth keeping: the
 * value only ever steers a post-login redirect, and grouping crash reports
 * by route never needed to know which path it pointed at, only that a
 * `next` was present. */
const SENSITIVE_QUERY_KEYS = new Set(["token", "code", "access_token", "refresh_token", "next"])

/** Path segments that are immediately followed, in this app's routes
 * (`routes.tsx`), by a credential: a password-reset token, an email-verify
 * token, a class invite code. The segment *after* one of these is redacted
 * regardless of what it looks like. */
const CREDENTIAL_PARENT_SEGMENTS = new Set(["reset", "verify-email", "join"])

/** A bare path segment that reads as a token or id even with no route
 * context — a UUID, an opaque signed string — rather than something a crash
 * report needs verbatim to be useful. 20 characters is long enough that no
 * ordinary route slug in this app (a slugified title, a short code) reaches
 * it by accident; grouping crash reports by route never needed the exact
 * identifier, only that two crashes shared a route shape. */
const OPAQUE_SEGMENT_PATTERN = /^[A-Za-z0-9_.~-]{20,}$/

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
 * Strip anything in the route that looks like a credential, keeping the
 * shape of the route (which screen this was) intact.
 *
 * Every credential this app puts in a URL at all is a *path* segment, not a
 * query parameter: `routes.tsx` mounts `/reset/:token`,
 * `/verify-email/:token` and `/join/:code`, and none of these routes sit
 * inside a portal `ErrorBoundary` (they are pre-auth, outside every portal
 * layout), so an uncaught render error on one of them reaches
 * `window.onerror` and this module directly — a crash on
 * `/reset/<real-token>` with no path redaction would write a live
 * password-reset token to Cloud Logging. Path redaction below is the fix
 * for that; query-key redaction (`SENSITIVE_QUERY_KEYS`) catches the
 * `?code=...`-shaped OAuth redirects this app also has.
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
 * is a defensive fallback, not a path this module expects to take. Note
 * also that `URLSearchParams#toString()` re-encodes every param it holds,
 * not just the one that changed, so a route with a redacted key can come
 * back with unrelated params re-percent-encoded (space as `+`, etc.) even
 * though their values are unchanged — harmless for a route used only to
 * group crash reports, but not a byte-for-byte round trip.
 */
export function redactRoute(route: string): string {
  const queryStart = route.indexOf("?")
  const rawPath = queryStart === -1 ? route : route.slice(0, queryStart)
  const query = queryStart === -1 ? null : route.slice(queryStart + 1)

  const redactedPath = rawPath
    .split("/")
    .map((segment, index, segments) => {
      if (OPAQUE_SEGMENT_PATTERN.test(segment)) return "redacted"
      const parent = segments[index - 1]
      if (parent !== undefined && CREDENTIAL_PARENT_SEGMENTS.has(parent)) return "redacted"
      return segment
    })
    .join("/")

  if (query === null) return redactedPath

  try {
    const params = new URLSearchParams(query)
    let redactedQuery = false
    for (const key of params.keys()) {
      if (SENSITIVE_QUERY_KEYS.has(key.toLowerCase())) {
        params.set(key, "redacted")
        redactedQuery = true
      }
    }
    if (!redactedQuery && redactedPath === rawPath) return route
    return `${redactedPath}?${params.toString()}`
  } catch {
    return redactedPath === rawPath ? route : `${redactedPath}?${query}`
  }
}

/** Read `getValue()`, falling back to `fallback` if it throws.
 *
 * Exists because every property this module reads off a caught value — an
 * `Error`'s `message`, its `stack`, a thrown object's `toString` (which is
 * what `String()` calls) — can be a getter or method the thrower itself
 * defined, and nothing stops one from throwing in turn. `describeThrown` is
 * the first thing `reportClientError` runs inside `componentDidCatch`; a
 * throw there would fail component recovery a second time and send the
 * original error straight past the boundary this whole module exists to
 * keep it from reaching.
 */
function safeRead<T>(getValue: () => T, fallback: T): T {
  try {
    return getValue()
  } catch {
    return fallback
  }
}

/** Extract a message + stack from anything a `catch`, `componentDidCatch` or
 * `window.onerror` can hand us. Non-`Error` throwables (a string, a plain
 * object, `undefined`) are real and reachable — `throw "oops"` is valid JS —
 * and `String(x)` is the same fallback `ApiError`'s own catch-all uses in
 * `lib/api.ts`, so a caught non-Error reads the same way here as it does
 * everywhere else in this client. Such a value never has a stack.
 *
 * Every read goes through `safeRead`: a null-prototype object
 * (`Object.create(null)`) has no inherited `toString`, so `String()` throws
 * on it; a plain object can define a `toString` that throws on purpose or
 * by accident; and an `Error` subclass can override `message`/`stack` as
 * accessors that throw. None of those are hypothetical enough to skip —
 * this function's whole job is to survive whatever `componentDidCatch` was
 * actually handed. An empty message is mapped to the literal "Unknown
 * error" rather than sent as `""`, because the backend's DTO for
 * `POST /api/client-errors` requires at least one character on `message`. */
function describeThrown(error: unknown): { message: string; stack: string | null } {
  const orUnknown = (message: string): string => (message === "" ? "Unknown error" : message)

  if (error instanceof Error) {
    const message = safeRead(() => error.message, "Unreportable error")
    const stack = safeRead(() => error.stack ?? null, null)
    return { message: orUnknown(message), stack }
  }
  const message = safeRead(() => String(error), "Unreportable error")
  return { message: orUnknown(message), stack: null }
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
   * these three fields agree. Joined with `\0`, the escape rather than a
   * literal NUL byte typed into the source: a literal one makes this file
   * look binary to line-oriented tools (`grep -r` reports "binary file
   * matches" instead of a normal hit), which is a bad trade for a separator
   * that only has to be a character none of the three joined fields
   * plausibly contains. */
  private static keyOf(report: Pick<ClientErrorReport, "message" | "stack" | "route">): string {
    return `${report.route}\0${report.message}\0${report.stack ?? ""}`
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
 *
 * Exported as of PR 2 part C: `lib/staleChunk.ts`'s reload guard and
 * `components/recovery-effects.tsx`'s "Updated" toast both need the exact
 * same build identity this module already computes, so they import it
 * rather than re-deriving the `__LEMELY_BUILD_ID__` guard a second time.
 */
export function currentBuildId(): string {
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
 *
 * The whole body runs inside a `try`/`catch` for the same reason
 * `describeThrown` reads every property defensively: this is the first
 * statement `ErrorBoundary.componentDidCatch` runs, and React re-throws
 * whatever a lifecycle method throws past the boundary that called it — so
 * a throw here would not just fail to report the original error, it would
 * take down the boundary that exists to contain it. `describeThrown` covers
 * the input; this covers everything else in the function (a `window` that
 * is unexpectedly absent, `JSON.stringify` on a value with a throwing
 * `toJSON`, `fetch` throwing synchronously rather than rejecting).
 */
export function reportClientError(input: {
  error: unknown
  kind: ClientErrorKind
  componentStack?: string | null
}): void {
  try {
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

    // `keepalive` requests share a 64 KiB in-flight body budget per origin
    // (the fetch spec's "keepalive" flag processing model), so a burst that
    // hits `MAX_REPORTS_PER_WINDOW` with sizeable stacks can have its 4th+
    // request rejected outright rather than sent. Accepted: the throttle
    // above already caps the burst at 5, and a rejected report fails the
    // same silent way a network failure does below.
    fetch("/api/client-errors", {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
    }).catch(() => {
      // Fire-and-forget, per the module doc above: a failed report is not
      // itself reportable.
    })
  } catch {
    // Per the module doc above: this function must not throw, full stop.
    // Nothing to fall back to here — the whole point of this path is that
    // it is the last line of defence, so a failure inside it is silent by
    // design, same as a dropped fetch.
  }
}

import { describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { classifyRouteError, parseRetryAfter, type RouteFailure } from "@/lib/routeError"

/*
 * PR 2 part A2 · `classifyRouteError`, pinned row by row against the
 * approved classification table.
 *
 * `isNotFoundResponse` and `attemptReload` are injected exactly as
 * `routeError.ts`'s own module doc explains: this suite never imports
 * `react-router-dom` or touches `window`, so a "thrown 404 Response" here is
 * a plain object the injected predicate recognises, and "a reload is under
 * way" is whatever the injected `attemptReload` mock returns.
 */

/** A stand-in for `isRouteErrorResponse(e) && e.status === 404`, matching a
 * plain marker object rather than a real react-router `ErrorResponse`. */
function isNotFoundResponse(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    (error as { status: unknown }).status === 404 &&
    "__routerErrorResponse" in error
  )
}

const NOT_FOUND_RESPONSE = { __routerErrorResponse: true, status: 404 }
const SERVER_ERROR_RESPONSE = { __routerErrorResponse: true, status: 500 }

function classify(
  error: unknown,
  opts: { online?: boolean; attemptReload?: (error: unknown) => boolean } = {},
): RouteFailure {
  return classifyRouteError(error, {
    online: opts.online ?? true,
    attemptReload: opts.attemptReload ?? (() => false),
    isNotFoundResponse,
  })
}

describe("classifyRouteError", () => {
  it("classifies no error at all as not-found", () => {
    expect(classify(undefined)).toEqual({ variant: "not-found" })
    expect(classify(null)).toEqual({ variant: "not-found" })
  })

  it("classifies a thrown 404 Response as not-found", () => {
    expect(classify(NOT_FOUND_RESPONSE)).toEqual({ variant: "not-found" })
  })

  it("does not classify a non-404 route Response as not-found", () => {
    expect(classify(SERVER_ERROR_RESPONSE)).not.toEqual({ variant: "not-found" })
  })

  describe("a chunk-load error", () => {
    const chunkError = new TypeError("Failed to fetch dynamically imported module: https://x/y.js")

    it("classifies as offline when the browser itself is offline, without attempting a reload", () => {
      const attemptReload = vi.fn(() => true)
      const result = classify(chunkError, { online: false, attemptReload })
      expect(result).toEqual({ variant: "offline" })
      expect(attemptReload).not.toHaveBeenCalled()
    })

    it("classifies as new-version with reloading:true when a guarded reload is under way", () => {
      const attemptReload = vi.fn(() => true)
      const result = classify(chunkError, { online: true, attemptReload })
      expect(result).toEqual({ variant: "new-version", reloading: true })
      expect(attemptReload).toHaveBeenCalledWith(chunkError)
    })

    it("classifies as new-version with no reloading flag when the guard declines (already spent)", () => {
      const attemptReload = vi.fn(() => false)
      const result = classify(chunkError, { online: true, attemptReload })
      expect(result).toEqual({ variant: "new-version" })
    })
  })

  describe("an ApiError", () => {
    it("maps 401 to session-ended", () => {
      expect(classify(new ApiError(401, "Unauthorized"))).toEqual({ variant: "session-ended" })
    })

    it("maps 403 to no-access", () => {
      expect(classify(new ApiError(403, "Forbidden"))).toEqual({ variant: "no-access" })
    })

    it("maps 429 to too-many-requests, carrying the parsed retryAfter", () => {
      const err = new ApiError(429, "Too Many Requests", undefined, 12)
      expect(classify(err)).toEqual({ variant: "too-many-requests", retryAfterSeconds: 12 })
    })

    it("defaults 429's countdown to 30s when the header carried no retryAfter", () => {
      const err = new ApiError(429, "Too Many Requests")
      expect(classify(err)).toEqual({ variant: "too-many-requests", retryAfterSeconds: 30 })
    })

    it("maps status 0 to offline when the browser is offline", () => {
      const err = new ApiError(0, "TypeError: Failed to fetch")
      expect(classify(err, { online: false })).toEqual({ variant: "offline" })
    })

    it("maps status 0 to service-trouble when the browser is online (the server itself is unreachable)", () => {
      const err = new ApiError(0, "TypeError: Failed to fetch")
      expect(classify(err, { online: true })).toEqual({ variant: "service-trouble" })
    })

    it.each([500, 502, 503, 504])("maps %i to service-trouble", (status) => {
      expect(classify(new ApiError(status, "Server Error"))).toEqual({ variant: "service-trouble" })
    })

    it("maps an unmapped 4xx (e.g. 400) to crash", () => {
      expect(classify(new ApiError(400, "Bad Request"))).toEqual({ variant: "crash" })
    })
  })

  describe("anything else", () => {
    it.each([
      ["a plain Error", new Error("boom")],
      ["a thrown string", "boom"],
      ["a plain object", { message: "oops" }],
    ])("classifies %s as crash", (_label, thrown) => {
      expect(classify(thrown)).toEqual({ variant: "crash" })
    })
  })
})

describe("parseRetryAfter", () => {
  const now = new Date("2026-09-02T12:00:00.000Z")

  it("returns null for a missing header", () => {
    expect(parseRetryAfter(null, now)).toBeNull()
  })

  it("returns null for an empty header", () => {
    expect(parseRetryAfter("", now)).toBeNull()
    expect(parseRetryAfter("   ", now)).toBeNull()
  })

  it("parses the delta-seconds form", () => {
    expect(parseRetryAfter("120", now)).toBe(120)
  })

  it("parses the delta-seconds form with surrounding whitespace", () => {
    expect(parseRetryAfter("  45  ", now)).toBe(45)
  })

  it("treats a delta of 0 as 0, not as absent", () => {
    expect(parseRetryAfter("0", now)).toBe(0)
  })

  it("parses an HTTP-date form relative to now", () => {
    expect(parseRetryAfter("Wed, 02 Sep 2026 12:02:00 GMT", now)).toBe(120)
  })

  it("clamps a past HTTP-date to 0 rather than a negative number", () => {
    expect(parseRetryAfter("Wed, 02 Sep 2026 11:00:00 GMT", now)).toBe(0)
  })

  it("returns null for unparseable garbage", () => {
    expect(parseRetryAfter("not a date or a number", now)).toBeNull()
    expect(parseRetryAfter("NaN", now)).toBeNull()
  })

  it("never returns a negative number for a negative delta-seconds string", () => {
    // "-30" fails the delta-seconds digit match and falls through to the
    // date parser, which also rejects it — both paths land on null, not a
    // negative number.
    expect(parseRetryAfter("-30", now)).toBeNull()
  })
})

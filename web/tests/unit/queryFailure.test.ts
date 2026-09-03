import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  describeQueryFailure,
  QUERY_ACCESS_DENIED,
  QUERY_GENERIC_FAILURE,
  QUERY_NETWORK_FAILURE,
  QUERY_NOT_FOUND,
  QUERY_RATE_LIMITED,
  QUERY_SERVICE_FAILURE,
  QUERY_SESSION_EXPIRED,
} from "@/lib/queryFailure"

/*
 * Loading/error primitives PR, part A · `<QueryState>`'s generic failure
 * sentence, pinned the same way `correctionOutcome.test.ts` pins the marking
 * flow's: every one of these is what a reader sees when a screen has no
 * outcome module of its own, so a silent regression here reaches ~47 screens
 * at once rather than one.
 */

describe("describeQueryFailure", () => {
  /*
   * These two pin the defect the module header now records: a detail-first
   * policy that is correct in `correctionOutcome.ts` (whose routes write
   * `detail` for a human) is wrong as this module's DEFAULT, because most of
   * `lemely/web/routers/`'s `detail`s are machine text — see
   * `studentOutcome.ts`'s header for the 154-site count. Both of these must
   * fall through to the status mapping, never echo the detail verbatim.
   */
  it("does not return a stringified-exception detail (str(exc)-style)", () => {
    // `placement.py`'s pattern: `HTTPException(422, detail=str(exc))`.
    const detail = "ValidationError: 1 validation error for StudentProfile"
    const err = new ApiError(422, detail, detail)
    const result = describeQueryFailure(err)
    expect(result).toBe(QUERY_GENERIC_FAILURE)
    expect(result).not.toBe(detail)
    expect(result).not.toContain("ValidationError")
  })

  it("does not return a Python-repr detail", () => {
    // `me.py`'s pattern: `f"Unknown session month: {value!r}"`.
    const detail = "Unknown session month: 'x'"
    const err = new ApiError(400, detail, detail)
    const result = describeQueryFailure(err)
    expect(result).toBe(QUERY_GENERIC_FAILURE)
    expect(result).not.toBe(detail)
    expect(result).not.toContain("'x'")
  })

  it("treats a structured (non-string) detail the same as a missing one", () => {
    // The placement 409's `detail` is a full DTO object, not a string — see
    // `studentOutcome.ts`'s header. This function must not stringify it.
    const err = new ApiError(409, "409 Conflict", { reason: "not_available" })
    expect(describeQueryFailure(err)).toBe(QUERY_GENERIC_FAILURE)
  })

  it("maps status 0 (no response at all) to the network sentence", () => {
    // `request()` wraps a fetch rejection as `ApiError(0, String(err))`.
    const err = new ApiError(0, "TypeError: Failed to fetch")
    expect(describeQueryFailure(err)).toBe(QUERY_NETWORK_FAILURE)
  })

  it("maps 401 to the session sentence", () => {
    const err = new ApiError(401, "Invalid access token: Signature has expired")
    expect(describeQueryFailure(err)).toBe(QUERY_SESSION_EXPIRED)
  })

  it("maps 403 to the access sentence", () => {
    const err = new ApiError(403, "Forbidden")
    expect(describeQueryFailure(err)).toBe(QUERY_ACCESS_DENIED)
  })

  it("maps 404 to the not-found sentence", () => {
    const err = new ApiError(404, "Not Found")
    expect(describeQueryFailure(err)).toBe(QUERY_NOT_FOUND)
  })

  it("maps 429 to the rate-limit sentence", () => {
    const err = new ApiError(429, "Too Many Requests")
    expect(describeQueryFailure(err)).toBe(QUERY_RATE_LIMITED)
  })

  it.each([500, 502, 503, 504])("maps %i to the service-failure sentence", (status) => {
    const err = new ApiError(status, `${status} Server Error`)
    expect(describeQueryFailure(err)).toBe(QUERY_SERVICE_FAILURE)
  })

  it("maps an unmapped 4xx to the generic fallback, without echoing the status", () => {
    const err = new ApiError(400, "400 Bad Request")
    expect(describeQueryFailure(err)).toBe(QUERY_GENERIC_FAILURE)
    expect(describeQueryFailure(err)).not.toContain("400")
  })

  it("never returns an ApiError's own synthesised status line", () => {
    const err = new ApiError(500, "500 Internal Server Error")
    expect(describeQueryFailure(err)).not.toContain("Internal Server Error")
  })

  /*
   * This is the defect the whole module exists to keep off the screen (see
   * `correctionOutcome.ts`'s header): rendering `error.message` verbatim for
   * whatever the runtime happened to throw. Every one of these must resolve
   * to this codebase's own sentence, never the argument's own wording.
   */
  it.each([
    ["a bare TypeError", new TypeError("Failed to fetch")],
    ["a Firefox-worded TypeError", new TypeError("NetworkError when attempting to fetch resource.")],
    ["a plain Error", new Error("ECONNRESET")],
    ["a thrown string", "boom"],
    ["undefined", undefined],
    ["null", null],
    ["a plain object", { message: "oops" }],
  ])("falls back to the generic sentence for %s, not its own message", (_label, thrown) => {
    expect(describeQueryFailure(thrown)).toBe(QUERY_GENERIC_FAILURE)
  })

  it("never returns an empty string, whatever it was handed", () => {
    for (const thrown of [undefined, null, "", 0, new Error("  "), {}]) {
      expect(describeQueryFailure(thrown).trim().length).toBeGreaterThan(0)
    }
  })

  /*
   * The no-em-dash/no-exclamation invariant runs over the function's actual
   * return values for every status class it distinguishes, not just the
   * exported constants — so a future branch that builds a sentence instead of
   * returning a constant (e.g. interpolating a status code) is still caught,
   * not just the seven names this file happens to import.
   */
  it("carries no em-dash and no exclamation mark in any returned sentence, for every status class", () => {
    const cases: unknown[] = [
      new ApiError(0, "network"),
      new ApiError(401, "unauthorized"),
      new ApiError(403, "forbidden"),
      new ApiError(404, "not found"),
      new ApiError(429, "too many requests"),
      new ApiError(500, "server error"),
      new ApiError(502, "bad gateway"),
      new ApiError(400, "bad request"),
      new TypeError("Failed to fetch"),
      undefined,
    ]
    for (const thrown of cases) {
      const sentence = describeQueryFailure(thrown)
      expect(sentence).not.toContain("—")
      expect(sentence).not.toContain("–")
      expect(sentence).not.toContain("!")
    }
  })
})

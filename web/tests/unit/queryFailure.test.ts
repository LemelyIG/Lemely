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
 * outcome module of its own, so a silent regression here reaches ~25 screens
 * at once rather than one.
 */

describe("describeQueryFailure", () => {
  it("prefers a backend detail written for a human", () => {
    const detail = "No mark scheme available for this paper; cannot mark."
    const err = new ApiError(422, detail, detail)
    expect(describeQueryFailure(err)).toBe(detail)
  })

  it("trims a detail string before returning it", () => {
    const err = new ApiError(422, "  Check the file and try again.  ", "  Check the file and try again.  ")
    expect(describeQueryFailure(err)).toBe("Check the file and try again.")
  })

  it("treats a whitespace-only detail as no detail", () => {
    const err = new ApiError(500, "500 Internal Server Error", "   ")
    expect(describeQueryFailure(err)).toBe(QUERY_SERVICE_FAILURE)
  })

  it("treats a structured (non-string) detail as no detail", () => {
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

  it("carries no em-dash and no exclamation mark in any returned sentence", () => {
    const sentences = [
      QUERY_NETWORK_FAILURE,
      QUERY_SESSION_EXPIRED,
      QUERY_ACCESS_DENIED,
      QUERY_NOT_FOUND,
      QUERY_RATE_LIMITED,
      QUERY_SERVICE_FAILURE,
      QUERY_GENERIC_FAILURE,
    ]
    for (const sentence of sentences) {
      expect(sentence).not.toContain("—")
      expect(sentence).not.toContain("–")
      expect(sentence).not.toContain("!")
    }
  })
})

import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { AUTH_EMAIL_UNVERIFIED } from "@/lib/authOutcome"
import {
  canRetryInPlace,
  correctionFailureMessage,
  NETWORK_FAILURE,
  SERVICE_FAILURE,
  STREAM_ENDED_WITHOUT_RESULT,
} from "@/lib/correctionOutcome"

/*
 * P4.2 · The failure vocabulary of the correct-a-paper flow.
 *
 * These are pinned rather than eyeballed because every one of them is a
 * sentence a fifteen-year-old reads at the moment their paper did not get
 * marked, and because the two defects behind them were both invisible: a run
 * that ended with no message at all, and a run that ended with the browser's
 * own words about a socket.
 */

describe("correctionFailureMessage", () => {
  it("prefers a backend detail written for a human", () => {
    // This is the real string `routers/student.py` publishes when it cannot
    // resolve a scheme, and it is the single most useful thing this screen can
    // say — far better than anything generic about a 422.
    const detail = "No mark scheme available for this paper; cannot mark."
    const err = new ApiError(422, detail, detail)
    expect(correctionFailureMessage(err)).toBe(detail)
  })

  it("does not show a synthesised status line", () => {
    // `api.ts` builds `message` as "500 Internal Server Error" when the body
    // carried no detail. Rendering that was the old behaviour.
    const err = new ApiError(500, "500 Internal Server Error")
    expect(correctionFailureMessage(err)).toBe(SERVICE_FAILURE)
    expect(correctionFailureMessage(err)).not.toContain("500")
  })

  it("treats a whitespace-only detail as no detail", () => {
    const err = new ApiError(503, "   ", "   ")
    expect(correctionFailureMessage(err)).toBe(SERVICE_FAILURE)
  })

  it("maps this codebase's status-0 wrapper to the network sentence", () => {
    // `request()` wraps a fetch rejection as `ApiError(0, String(err))`, whose
    // message is the raw "TypeError: Failed to fetch".
    const err = new ApiError(0, "TypeError: Failed to fetch")
    expect(correctionFailureMessage(err)).toBe(NETWORK_FAILURE)
  })

  it("maps a bare fetch rejection to the same network sentence", () => {
    expect(correctionFailureMessage(new TypeError("Failed to fetch"))).toBe(NETWORK_FAILURE)
    // Firefox words the identical condition differently. A reader must not get
    // two different explanations of one problem depending on their browser.
    expect(
      correctionFailureMessage(new TypeError("NetworkError when attempting to fetch resource.")),
    ).toBe(NETWORK_FAILURE)
  })

  it("names D7.5's gate instead of pleading ignorance about it", () => {
    // The one 403 `POST /student/correct` actually raises. Reproduced against
    // staging on 2026-09-04: the run stopped with "turned this run down and
    // didn't say why" while the response body said, in as many words, why —
    // `{"detail":{"code":"email_unverified"}}`. `deps.require_verified_email`
    // documents that marker as the thing "the frontend's `lib/authOutcome.ts`-
    // family outcome modules match on", and no module on this screen's path
    // ever did.
    const err = new ApiError(403, "403 Forbidden", { code: "email_unverified" })
    expect(correctionFailureMessage(err)).toBe(AUTH_EMAIL_UNVERIFIED)
  })

  it("does not mistake any other 403 for the verification gate", () => {
    // `require_role`'s 403 carries a prose detail, not the marker. It must
    // keep going through the detail-first branch above, or a student would be
    // told to check their inbox about a permissions problem.
    const detail = "Your role is not permitted to access this resource"
    expect(correctionFailureMessage(new ApiError(403, detail, detail))).toBe(detail)
    expect(correctionFailureMessage(new ApiError(403, "403 Forbidden"))).toContain("didn't say why")
  })

  it("keeps a 4xx honest about what it does not know", () => {
    const message = correctionFailureMessage(new ApiError(409, "409 Conflict"))
    expect(message).toContain("didn't say why")
    expect(message).not.toContain("409")
  })

  it("never returns an empty string, whatever it was handed", () => {
    for (const thrown of [undefined, null, "", 0, new Error("  "), {}]) {
      expect(correctionFailureMessage(thrown).trim().length).toBeGreaterThan(0)
    }
  })
})

describe("STREAM_ENDED_WITHOUT_RESULT", () => {
  it("tells the student their scan survived, because that is what makes retry cheap", () => {
    expect(STREAM_ENDED_WITHOUT_RESULT).toContain("still uploaded")
  })

  it("is written in active voice and carries no em-dash", () => {
    // MISSION §3.2 item 10. The copy gate greps source files; this pins the
    // constant itself so a later edit cannot reintroduce one here.
    expect(STREAM_ENDED_WITHOUT_RESULT).not.toContain("—")
    expect(STREAM_ENDED_WITHOUT_RESULT).not.toContain("!")
  })
})

describe("canRetryInPlace", () => {
  it("is true only for a real uploaded paper id", () => {
    expect(canRetryInPlace("paper-123")).toBe(true)
    expect(canRetryInPlace("")).toBe(false)
    expect(canRetryInPlace(null)).toBe(false)
  })
})

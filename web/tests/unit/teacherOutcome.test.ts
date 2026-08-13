import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  TEACHER_NETWORK_FAILURE,
  TEACHER_SERVICE_FAILURE,
  teacherLoadFailureMessage,
  teacherMutationFailureMessage,
} from "@/lib/teacherOutcome"

/*
 * P4.5 · The failure vocabulary of the teacher portal.
 *
 * The third module in the family, and the one with the widest reach: every
 * one of the portal's fifteen screens rendered a raw `error.message`, at 44
 * call sites. These are pinned rather than eyeballed for the same reason the
 * student modules are — the sentences appear at the moment something did not
 * work, which is exactly when nobody is in a position to interpret
 * `TypeError: Failed to fetch`.
 */

describe("teacherLoadFailureMessage", () => {
  it("prefers a backend detail written for a human", () => {
    // A 403 on a class that is not this teacher's says far more than any
    // sentence written in the frontend could.
    const detail = "You do not have access to this class."
    expect(teacherLoadFailureMessage(new ApiError(403, detail, detail))).toBe(detail)
  })

  it("names the connection when there was no response at all", () => {
    // `request()` wraps a fetch rejection as `ApiError(0, ...)`, so status 0
    // is this codebase's spelling of "nothing came back".
    expect(teacherLoadFailureMessage(new ApiError(0, "Failed to fetch"))).toBe(
      TEACHER_NETWORK_FAILURE,
    )
  })

  it("does not blame the teacher for a server fault", () => {
    expect(teacherLoadFailureMessage(new ApiError(500, "Internal Server Error"))).toBe(
      TEACHER_SERVICE_FAILURE,
    )
  })

  it("never puts a bare TypeError on screen", () => {
    // The exact defect: a dropped connection reaching the DOM as the
    // browser's own words about a socket.
    const message = teacherLoadFailureMessage(new TypeError("Failed to fetch"))
    expect(message).toBe(TEACHER_NETWORK_FAILURE)
    expect(message).not.toContain("TypeError")
    expect(message).not.toContain("fetch")
  })

  it("says something useful about an error it cannot classify", () => {
    expect(teacherLoadFailureMessage(new Error("kaboom"))).not.toContain("kaboom")
    expect(teacherLoadFailureMessage(undefined)).toMatch(/couldn't load/i)
  })
})

describe("teacherMutationFailureMessage", () => {
  it("keeps the endpoint's own words where it wrote some", () => {
    // The at-risk acknowledge route's real 422: a genuine race when the
    // evidence moved between the list loading and the click. No sentence
    // written here could reconstruct that.
    const detail = "That reason is not currently firing for this student."
    expect(teacherMutationFailureMessage(new ApiError(422, detail, detail))).toBe(detail)
  })

  it("states that nothing was saved on every branch it owns the wording of", () => {
    // The question a teacher actually has after a failed write. Every
    // mutation in this portal is a single request, so "nothing was saved" is
    // true rather than reassuring.
    for (const err of [
      new ApiError(0, "Failed to fetch"),
      new ApiError(503, "Service Unavailable"),
      new ApiError(400, ""),
      new TypeError("Failed to fetch"),
    ]) {
      expect(teacherMutationFailureMessage(err)).toMatch(/nothing was saved/i)
    }
  })

  it("does not claim nothing was saved when the server said what happened", () => {
    // The one branch where the backend's sentence is passed through: adding
    // "Nothing was saved" to it would be asserting something this module
    // cannot know, since a 409 may well mean the opposite.
    const detail = "A quiz with that name already exists."
    expect(teacherMutationFailureMessage(new ApiError(409, detail, detail))).toBe(detail)
  })

  it("reads differently from the load message, because the questions differ", () => {
    // A failed read asks "can I retry"; a failed write asks "did it save".
    // If these two ever collapse into one sentence, one of the questions has
    // stopped being answered.
    const network = new ApiError(0, "Failed to fetch")
    expect(teacherMutationFailureMessage(network)).not.toBe(teacherLoadFailureMessage(network))
  })
})

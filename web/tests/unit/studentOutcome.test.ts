import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { STUDENT_RESTORE_WINDOW_CLOSED, studentSaveFailureMessage } from "@/lib/studentOutcome"

/*
 * Task 14 review, Minor 1: `studentSaveFailureMessage` had no 410 case, so a
 * restore past its window (or already purged by the sweeper) fell into the
 * generic "Something went wrong on our side" — wrong on its face (nothing
 * is wrong on our side; the window is just closed) and misleading (it reads
 * as retryable, which a 410 never is).
 */
describe("studentSaveFailureMessage — 410", () => {
  it("names the closed restore window specifically, not the generic failure", () => {
    const err = new ApiError(410, "Gone")
    expect(studentSaveFailureMessage(err)).toBe(STUDENT_RESTORE_WINDOW_CLOSED)
  })

  it("says nothing about why, matching the reason-free deletion copy elsewhere", () => {
    expect(STUDENT_RESTORE_WINDOW_CLOSED).not.toMatch(/review|flag|plagiar|integrity|score/i)
  })

  it("other statuses are unaffected", () => {
    expect(studentSaveFailureMessage(new ApiError(422, "Unprocessable"))).not.toBe(
      STUDENT_RESTORE_WINDOW_CLOSED,
    )
  })
})

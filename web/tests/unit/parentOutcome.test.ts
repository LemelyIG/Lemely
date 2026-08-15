import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  PARENT_NETWORK_FAILURE,
  PARENT_NOT_FOUND,
  PARENT_NOT_LINKED,
  PARENT_SERVICE_FAILURE,
  parentLoadFailureMessage,
} from "@/lib/parentOutcome"
import { gradeArticle } from "@/portals/parent/screens/SubjectDetail"

/*
 * P4.6 · the parent portal's failure copy, and the one copy defect the capture
 * round caught.
 */

describe("parentLoadFailureMessage", () => {
  it("names a lost connection as a connection problem", () => {
    // `request()` wraps a fetch rejection as ApiError(0, …), so status 0 is
    // this codebase's spelling of "no response at all".
    expect(parentLoadFailureMessage(new ApiError(0, "Failed to fetch"))).toBe(
      PARENT_NETWORK_FAILURE,
    )
    expect(parentLoadFailureMessage(new TypeError("Failed to fetch"))).toBe(
      PARENT_NETWORK_FAILURE,
    )
  })

  it("turns a 403 into a sentence about the link, not about permission", () => {
    const err = new ApiError(403, "Forbidden", "Child 6f2c1b7e is not linked to this parent")
    expect(parentLoadFailureMessage(err)).toBe(PARENT_NOT_LINKED)
  })

  it("turns a 404 into a sentence about the thing being gone", () => {
    expect(parentLoadFailureMessage(new ApiError(404, "Not Found", "Unknown child: 6f2c"))).toBe(
      PARENT_NOT_FOUND,
    )
  })

  it("says a 5xx is ours and safe to retry", () => {
    expect(parentLoadFailureMessage(new ApiError(503, "Service Unavailable"))).toBe(
      PARENT_SERVICE_FAILURE,
    )
  })

  /**
   * The whole reason this module exists rather than reusing `teacherOutcome`.
   *
   * Every `detail` the parent API can produce is machine text — a raw UUID or a
   * stringified Python exception — so a detail-first classifier would put
   * `Child 6f2c1b7e-… is not linked to this parent` in front of a parent. This
   * asserts the negative directly: no branch may echo the server's detail.
   */
  it("never echoes the endpoint's own detail, which is always machine text here", () => {
    const details = [
      "Child 6f2c1b7e-9a1d-4d2f-8e77-2b0c5f1e9a33 is not linked to this parent",
      "Unknown child: 6f2c1b7e-9a1d-4d2f-8e77-2b0c5f1e9a33",
      "No papers for subject 0625",
      "ValueError: time data '2026-13-01' does not match format '%Y-%m-%d'",
    ]
    for (const [index, detail] of details.entries()) {
      const status = [403, 404, 404, 422][index]
      const message = parentLoadFailureMessage(new ApiError(status, "err", detail))
      expect(message).not.toContain(detail)
      expect(message).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/)
      expect(message).not.toContain("ValueError")
    }
  })

  it("falls back to a sentence for anything it cannot classify", () => {
    const message = parentLoadFailureMessage(new Error("boom"))
    expect(message).toContain("couldn't load this")
    expect(message).not.toContain("boom")
  })
})

describe("gradeArticle", () => {
  /**
   * The capture round photographed "6 more marks for a A" on the subject
   * screen, which is what a hardcoded article produces for precisely the grades
   * a parent most wants to read about.
   */
  it("uses 'an' for the grades whose letter names begin with a vowel sound", () => {
    for (const grade of ["A", "A*", "E", "F"]) {
      expect(gradeArticle(grade), grade).toBe("an")
    }
  })

  it("uses 'a' for the rest, including U, which a naive vowel test would get wrong", () => {
    for (const grade of ["B", "C", "D", "G", "U"]) {
      expect(gradeArticle(grade), grade).toBe("a")
    }
  })

  it("tolerates the whitespace a backend string can carry", () => {
    expect(gradeArticle(" A ")).toBe("an")
    expect(gradeArticle(" C")).toBe("a")
  })
})

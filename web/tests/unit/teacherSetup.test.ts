import { describe, expect, it } from "vitest"
import { deriveSetup } from "@/portals/teacher/home/setup"

describe("deriveSetup", () => {
  it.each([
    // classes, papers, pending, created, uploaded, reviewed, done
    [0, 0, 0, false, false, false, 0],
    [1, 0, 0, true, false, false, 1],
    [1, 3, 5, true, true, false, 2],
    [1, 3, 0, true, true, true, 3],
    [0, 3, 0, false, true, true, 2],
  ])("classes=%i papers=%i pending=%i", (classes, papers, pending, created, uploaded, reviewed, done) => {
    const s = deriveSetup(classes, { paperCount: papers, pendingReviewCount: pending })
    expect(s).toEqual({ created, uploaded, reviewed, done, complete: done === 3 })
  })

  it("never counts review as done before any paper exists", () => {
    expect(deriveSetup(2, { paperCount: 0, pendingReviewCount: 0 }).reviewed).toBe(false)
  })
})

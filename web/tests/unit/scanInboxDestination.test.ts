import { describe, expect, it } from "vitest"
import { scanInboxDestination } from "../../src/lib/scanInboxDestination.ts"

/**
 * The role-aware landing `/scan-inbox` (`routes.tsx`) resolves to via this
 * pure function — both the Web Share Target redirect (`shareTarget.ts`) and
 * the File Handling API route used to hardcode `/student/correct`, which
 * left a teacher who shared or opened a scan on a no-access page while the
 * stashed file quietly expired.
 */
describe("scanInboxDestination", () => {
  it("sends a student to the correction flow", () => {
    expect(scanInboxDestination("student")).toBe("/student/correct")
  })

  it("sends a teacher to the grading console — their real upload surface", () => {
    expect(scanInboxDestination("teacher")).toBe("/teacher/grading")
  })

  it("falls back to the student route with no session, so RequireAuth sends a signed-out reader to /login", () => {
    expect(scanInboxDestination(null)).toBe("/student/correct")
  })

  it("falls back to a role's own portal home for roles with no scan-upload surface", () => {
    expect(scanInboxDestination("parent")).toBe("/parent")
    expect(scanInboxDestination("school_admin")).toBe("/school")
    expect(scanInboxDestination("platform_admin")).toBe("/platform")
  })
})

import { describe, expect, it } from "vitest"
import { scanInboxDestination, scanInboxLandingFor } from "../../src/lib/scanInboxDestination.ts"

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

  it("sends a school_admin to the grading console too — TEACHER_ROLES (routes.tsx) grants them /teacher/grading, so the same no-access bug applies", () => {
    expect(scanInboxDestination("school_admin")).toBe("/teacher/grading")
  })

  it("falls back to the student route with no session, so RequireAuth sends a signed-out reader to /login", () => {
    expect(scanInboxDestination(null)).toBe("/student/correct")
  })

  it("falls back to a role's own portal home for roles with no scan-upload surface", () => {
    expect(scanInboxDestination("parent")).toBe("/parent")
    expect(scanInboxDestination("platform_admin")).toBe("/platform")
  })
})

describe("scanInboxLandingFor", () => {
  it("resolves a signed-in reader's role exactly like scanInboxDestination", () => {
    expect(scanInboxLandingFor("teacher")).toBe("/teacher/grading")
    expect(scanInboxLandingFor("student")).toBe("/student/correct")
  })

  it("sends a signed-out reader to /login with next=/scan-inbox — not straight to /student/correct — so the role is re-resolved AFTER sign-in instead of freezing to the student destination before it's known", () => {
    expect(scanInboxLandingFor(null)).toBe("/login?next=%2Fscan-inbox")
  })
})

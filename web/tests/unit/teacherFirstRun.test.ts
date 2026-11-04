import { describe, expect, it } from "vitest"
import { teacherHomeView } from "@/portals/teacher/home/TeacherHome"

/*
 * The teacher home chooses between the setup screen and the overview. The
 * old D7.10 gate redirected a zero-class teacher to /teacher/first-class; the
 * setup screen replaces it. The pending/error discipline is kept: a query
 * that has not resolved, or has failed, must never read as "no classes yet".
 */
describe("teacherHomeView", () => {
  const ready = { paperCount: 0, pendingReviewCount: 0 }
  it("waits while either query is pending", () => {
    expect(teacherHomeView("pending", 0, "success", ready)).toBe("loading")
    expect(teacherHomeView("success", 0, "pending", undefined)).toBe("loading")
  })
  it("shows an error, never setup, when a query failed", () => {
    expect(teacherHomeView("error", 0, "success", ready)).toBe("error")
    expect(teacherHomeView("success", 2, "error", undefined)).toBe("error")
  })
  it("shows setup for a zero-class teacher instead of redirecting", () => {
    expect(teacherHomeView("success", 0, "success", ready)).toBe("setup")
  })
  it("shows the overview once a class and a paper exist, even with items pending", () => {
    expect(teacherHomeView("success", 1, "success", { paperCount: 3, pendingReviewCount: 4 })).toBe("overview")
    expect(teacherHomeView("success", 1, "success", { paperCount: 0, pendingReviewCount: 0 })).toBe("setup")
  })
})

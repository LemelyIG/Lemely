import { describe, expect, it } from "vitest"
import { scrollRestorationKey, TAB_ROOTS } from "@/lib/nav/scrollRestorationKey"

/*
 * Packet B2a · `<ScrollRestoration getKey={...}>` (mounted once in
 * `RootOutlet`). A tab-root pathname (Task 4 populates `TAB_ROOTS`) restores
 * scroll by pathname — switching tabs and back keeps the previous scroll
 * position — while every other route restores by the router's per-entry
 * `location.key`, the default `<ScrollRestoration>` behaviour.
 */

describe("scrollRestorationKey", () => {
  it("keys a tab-root pathname by the pathname itself", () => {
    const tabRoots = new Set(["/student", "/student/classes"])
    expect(
      scrollRestorationKey({ pathname: "/student", key: "abc123" }, tabRoots),
    ).toBe("/student")
  })

  it("keys a non-tab-root route by its location key", () => {
    const tabRoots = new Set(["/student"])
    expect(
      scrollRestorationKey({ pathname: "/student/subject/1", key: "abc123" }, tabRoots),
    ).toBe("abc123")
  })

  it("defaults to the module TAB_ROOTS when none is passed", () => {
    // Packet B3 (Task 4) filled TAB_ROOTS with the BottomNav/SidebarNav
    // tab roots, so the module default now keys /student by its pathname.
    expect(scrollRestorationKey({ pathname: "/student", key: "xyz789" })).toBe("/student")
  })

  it("Task 4 (B3) fills TAB_ROOTS with the student and teacher tab roots", () => {
    expect([...TAB_ROOTS].sort()).toEqual(
      [
        "/student",
        "/student/correct",
        "/student/classes",
        "/student/profile",
        "/teacher",
        "/teacher/grading",
        "/teacher/review",
        "/teacher/classes",
      ].sort(),
    )
  })
})

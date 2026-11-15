import { describe, expect, it } from "vitest"
import { recordHistoryPath, stepsBackToRoot } from "@/lib/nav/historyPaths"

describe("stepsBackToRoot", () => {
  it("counts back to the tab root through the root's own drill run", () => {
    recordHistoryPath(10, "/teacher/classes")
    recordHistoryPath(11, "/teacher/classes/c1")
    recordHistoryPath(12, "/teacher/classes/c1/papers")
    expect(stepsBackToRoot(11, "/teacher/classes")).toBe(1)
    expect(stepsBackToRoot(12, "/teacher/classes")).toBe(2)
  })

  it("is null when another section sits between, or the root was never entered", () => {
    recordHistoryPath(20, "/teacher/classes")
    recordHistoryPath(21, "/teacher/review")
    recordHistoryPath(22, "/teacher/classes/c1")
    expect(stepsBackToRoot(22, "/teacher/classes")).toBeNull()
    recordHistoryPath(31, "/teacher/classes/c1")
    expect(stepsBackToRoot(31, "/teacher/classes")).toBeNull()
    expect(stepsBackToRoot(undefined, "/teacher/classes")).toBeNull()
  })

  it("does not take a sibling path that only shares a prefix for the same section", () => {
    recordHistoryPath(40, "/teacher/classes")
    recordHistoryPath(41, "/teacher/classes-archive")
    recordHistoryPath(42, "/teacher/classes/c1")
    expect(stepsBackToRoot(42, "/teacher/classes")).toBeNull()
  })
})

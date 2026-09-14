import { describe, expect, it } from "vitest"
import { quizSwipeAllowed } from "@/lib/quizSwipe"

describe("quizSwipeAllowed — last-60-seconds lock", () => {
  it("59 seconds remaining locks the swipe", () => {
    expect(
      quizSwipeAllowed({ remainingSeconds: 59, targetTag: "DIV", targetRole: null }),
    ).toBe(false)
  })

  it("inverse: 61 seconds remaining allows the swipe", () => {
    expect(
      quizSwipeAllowed({ remainingSeconds: 61, targetTag: "DIV", targetRole: null }),
    ).toBe(true)
  })

  it("exactly 60 seconds remaining locks the swipe (the lock is inclusive)", () => {
    expect(
      quizSwipeAllowed({ remainingSeconds: 60, targetTag: "DIV", targetRole: null }),
    ).toBe(false)
  })

  it("no time limit at all (null) never locks the swipe", () => {
    expect(
      quizSwipeAllowed({ remainingSeconds: null, targetTag: "DIV", targetRole: null }),
    ).toBe(true)
  })
})

describe("quizSwipeAllowed — interactive targets are never swiped away from", () => {
  it.each(["TEXTAREA", "INPUT", "BUTTON", "A"])("a %s target refuses the swipe", (tag) => {
    expect(
      quizSwipeAllowed({ remainingSeconds: null, targetTag: tag, targetRole: null }),
    ).toBe(false)
  })

  it("a role=radio target refuses the swipe regardless of its tag", () => {
    expect(
      quizSwipeAllowed({ remainingSeconds: null, targetTag: "BUTTON", targetRole: "radio" }),
    ).toBe(false)
  })

  it("inverse: a plain non-interactive target with no role allows the swipe", () => {
    expect(
      quizSwipeAllowed({ remainingSeconds: null, targetTag: "DIV", targetRole: null }),
    ).toBe(true)
  })

  it("lowercase tag names are matched case-insensitively", () => {
    expect(
      quizSwipeAllowed({ remainingSeconds: null, targetTag: "button", targetRole: null }),
    ).toBe(false)
  })
})

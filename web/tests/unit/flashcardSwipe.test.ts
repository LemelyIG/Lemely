import { describe, expect, it } from "vitest"
import { flashcardSwipeAction } from "@/lib/flashcardSwipe"

describe("flashcardSwipeAction — unrevealed: swipe up or right reveals, nothing grades before reveal", () => {
  it("swipe up past the -60 threshold reveals", () => {
    expect(flashcardSwipeAction({ dx: 0, dy: -60, revealed: false })).toBe("reveal")
  })

  it("inverse: swipe up short of the threshold does nothing", () => {
    expect(flashcardSwipeAction({ dx: 0, dy: -59, revealed: false })).toBe("none")
  })

  it("swipe right past the 60 threshold reveals", () => {
    expect(flashcardSwipeAction({ dx: 60, dy: 0, revealed: false })).toBe("reveal")
  })

  it("inverse: swipe right short of the threshold does nothing", () => {
    expect(flashcardSwipeAction({ dx: 59, dy: 0, revealed: false })).toBe("none")
  })

  it("a leftward swipe never reveals — reveal is only up or right", () => {
    expect(flashcardSwipeAction({ dx: -100, dy: 0, revealed: false })).toBe("none")
  })

  it("no swipe before reveal is ever graded, however large", () => {
    expect(flashcardSwipeAction({ dx: -200, dy: 0, revealed: false })).not.toBe("again")
    expect(flashcardSwipeAction({ dx: 200, dy: 0, revealed: false })).not.toBe("good")
  })
})

describe("flashcardSwipeAction — revealed: left grades again, right grades good", () => {
  it("swipe left past the -80 threshold grades again", () => {
    expect(flashcardSwipeAction({ dx: -80, dy: 0, revealed: true })).toBe("again")
  })

  it("inverse: swipe left short of the threshold does nothing", () => {
    expect(flashcardSwipeAction({ dx: -79, dy: 0, revealed: true })).toBe("none")
  })

  it("swipe right past the 80 threshold grades good", () => {
    expect(flashcardSwipeAction({ dx: 80, dy: 0, revealed: true })).toBe("good")
  })

  it("inverse: swipe right short of the threshold does nothing", () => {
    expect(flashcardSwipeAction({ dx: 79, dy: 0, revealed: true })).toBe("none")
  })

  it("a reveal-shaped upward swipe does nothing once already revealed", () => {
    expect(flashcardSwipeAction({ dx: 0, dy: -200, revealed: true })).toBe("none")
  })
})

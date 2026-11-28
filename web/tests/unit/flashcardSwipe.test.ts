import { describe, expect, it } from "vitest"
import { flashcardSwipeAction, GRADE_SWIPE_THRESHOLD, REVEAL_SWIPE_THRESHOLD, swipeVisual } from "@/lib/flashcardSwipe"

/*
 * Consolidation pass · this used to also take a `dy` and reveal on `dy <=
 * -60`, alongside a `FlashcardReview.tsx` comment claiming that branch was
 * "reachable via a diagonal drag". Checked against `useDragGesture`'s own
 * commit gate (`shouldCommitDrag`, axis "x"): the branch a plain up-swipe
 * test (`dx: 0, dy: -60`) exercised can in fact never commit at all under
 * `axis: "x"` (it requires `|dx| > 2|dy|`), and the one diagonal that *can*
 * reach it is a drag whose horizontal component dominates and is *negative*
 * — i.e. a predominantly leftward drag with enough upward tilt — which is
 * exactly the direction the "a leftward swipe never reveals" case below
 * says must never reveal. Real bug, not dead code; fixed by dropping `dy`
 * from the decision entirely rather than growing this into a two-axis
 * gesture system for a single vertical shortcut.
 */
describe("flashcardSwipeAction — unrevealed: only a rightward swipe reveals", () => {
  it(`swipe right past the ${REVEAL_SWIPE_THRESHOLD} threshold reveals`, () => {
    expect(flashcardSwipeAction({ dx: REVEAL_SWIPE_THRESHOLD, revealed: false })).toBe("reveal")
  })

  it("inverse: swipe right short of the threshold does nothing", () => {
    expect(flashcardSwipeAction({ dx: REVEAL_SWIPE_THRESHOLD - 1, revealed: false })).toBe("none")
  })

  it("a leftward swipe never reveals", () => {
    expect(flashcardSwipeAction({ dx: -100, revealed: false })).toBe("none")
  })

  it("no swipe before reveal is ever graded, however large", () => {
    expect(flashcardSwipeAction({ dx: -200, revealed: false })).not.toBe("again")
    expect(flashcardSwipeAction({ dx: 200, revealed: false })).not.toBe("good")
  })
})

describe("flashcardSwipeAction — revealed: left grades again, right grades good", () => {
  it(`swipe left past the -${GRADE_SWIPE_THRESHOLD} threshold grades again`, () => {
    expect(flashcardSwipeAction({ dx: -GRADE_SWIPE_THRESHOLD, revealed: true })).toBe("again")
  })

  it("inverse: swipe left short of the threshold does nothing", () => {
    expect(flashcardSwipeAction({ dx: -GRADE_SWIPE_THRESHOLD + 1, revealed: true })).toBe("none")
  })

  it(`swipe right past the ${GRADE_SWIPE_THRESHOLD} threshold grades good`, () => {
    expect(flashcardSwipeAction({ dx: GRADE_SWIPE_THRESHOLD, revealed: true })).toBe("good")
  })

  it("inverse: swipe right short of the threshold does nothing", () => {
    expect(flashcardSwipeAction({ dx: GRADE_SWIPE_THRESHOLD - 1, revealed: true })).toBe("none")
  })
})

describe("swipeVisual", () => {
  it("shows no stamp before the flip", () => {
    expect(swipeVisual(120, false, false)).toEqual({ stamp: null, opacity: 0, rotateDeg: 6, armed: false })
  })
  it("fades the Good stamp in to the grade threshold, then arms", () => {
    expect(swipeVisual(40, true, false)).toEqual({ stamp: "good", opacity: 0.5, rotateDeg: 3.2, armed: false })
    expect(swipeVisual(GRADE_SWIPE_THRESHOLD, true, false).armed).toBe(true)
  })
  it("stamps Again to the left and caps the tilt", () => {
    expect(swipeVisual(-400, true, false)).toEqual({ stamp: "again", opacity: 1, rotateDeg: -12, armed: true })
  })
  it("never tilts under reduced motion", () => {
    expect(swipeVisual(-400, true, true).rotateDeg).toBe(0)
    expect(swipeVisual(120, false, true).rotateDeg).toBe(0)
  })
})

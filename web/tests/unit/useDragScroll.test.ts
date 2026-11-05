import { describe, expect, it } from "vitest"
import { DRAG_THRESHOLD, dragScrollLeft, isDragMove } from "@/portals/teacher/home/useDragScroll"

describe("useDragScroll pure logic", () => {
  it("treats travel at or under the threshold as a click", () => {
    expect(isDragMove(100, 100 + DRAG_THRESHOLD)).toBe(false)
    expect(isDragMove(100, 100 - DRAG_THRESHOLD)).toBe(false)
  })
  it("treats travel past the threshold in either direction as a drag", () => {
    expect(isDragMove(100, 100 + DRAG_THRESHOLD + 1)).toBe(true)
    expect(isDragMove(100, 100 - DRAG_THRESHOLD - 1)).toBe(true)
  })
  it("moves scrollLeft opposite to the pointer", () => {
    expect(dragScrollLeft(200, 500, 450)).toBe(250)
    expect(dragScrollLeft(200, 500, 560)).toBe(140)
  })
})

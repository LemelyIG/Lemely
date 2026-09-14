import { describe, expect, it } from "vitest"
import { queuePosition } from "@/lib/queuePosition"

/*
 * Task 9 (C3d) · `queuePosition` — the data behind `ReviewItem.tsx`'s
 * "Item N of total" strip and its Prev/Next links.
 */

const IDS = ["a", "b", "c", "d"] as const

describe("queuePosition", () => {
  it("the first item has no prev, a next", () => {
    expect(queuePosition(IDS, "a")).toEqual({ index: 0, total: 4, prevId: null, nextId: "b" })
  })

  it("a middle item has both prev and next", () => {
    expect(queuePosition(IDS, "b")).toEqual({ index: 1, total: 4, prevId: "a", nextId: "c" })
    expect(queuePosition(IDS, "c")).toEqual({ index: 2, total: 4, prevId: "b", nextId: "d" })
  })

  it("the last item has a prev, no next", () => {
    expect(queuePosition(IDS, "d")).toEqual({ index: 3, total: 4, prevId: "c", nextId: null })
  })

  it("is null when the id isn't in the queue at all", () => {
    expect(queuePosition(IDS, "missing")).toBeNull()
  })

  it("is null on an empty queue", () => {
    expect(queuePosition([], "a")).toBeNull()
  })

  it("a single-item queue has neither prev nor next", () => {
    expect(queuePosition(["only"], "only")).toEqual({
      index: 0,
      total: 1,
      prevId: null,
      nextId: null,
    })
  })
})

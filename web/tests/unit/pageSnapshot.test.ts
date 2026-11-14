import { describe, expect, it } from "vitest"
import { SNAPSHOT_LIMIT, SNAPSHOT_NODE_CAP, createSnapshotStore, withinNodeCap } from "@/lib/nav/pageSnapshot"

describe("snapshot store", () => {
  it("keeps the most recently used entries within the limit", () => {
    const store = createSnapshotStore<string>(3)
    store.set(1, "a")
    store.set(2, "b")
    store.set(3, "c")
    store.get(1)
    store.set(4, "d")
    expect(store.keys().sort()).toEqual([1, 3, 4])
  })
  it("defaults to five entries", () => {
    const store = createSnapshotStore<number>()
    for (let i = 0; i < 9; i++) store.set(i, i)
    expect(store.keys()).toHaveLength(SNAPSHOT_LIMIT)
    expect(SNAPSHOT_LIMIT).toBe(5)
  })
  it("a push drops the entry at its index and everything beyond", () => {
    const store = createSnapshotStore<string>()
    for (const i of [1, 2, 3, 4]) store.set(i, String(i))
    store.dropFrom(3)
    expect(store.keys().sort()).toEqual([1, 2])
    store.delete(1)
    expect(store.get(1)).toBeUndefined()
  })
  it("refuses a column over the node cap", () => {
    expect(withinNodeCap(SNAPSHOT_NODE_CAP)).toBe(true)
    expect(withinNodeCap(SNAPSHOT_NODE_CAP + 1)).toBe(false)
  })
})

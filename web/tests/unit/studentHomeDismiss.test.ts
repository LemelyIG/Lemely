import { describe, expect, it } from "vitest"
import { DISMISS_KEY, readDismissed, writeDismissed } from "@/portals/student/home/dismiss"

function memory(): Storage {
  const map = new Map<string, string>()
  return {
    get length() {
      return map.size
    },
    clear: () => map.clear(),
    getItem: (k) => map.get(k) ?? null,
    key: (i) => [...map.keys()][i] ?? null,
    removeItem: (k) => void map.delete(k),
    setItem: (k, v) => void map.set(k, v),
  }
}

describe("Not now memory", () => {
  it("round-trips keys for the same day", () => {
    const s = memory()
    writeDismissed(s, "2026-11-12", new Set(["result:5"]))
    expect([...readDismissed(s, "2026-11-12")]).toEqual(["result:5"])
  })

  it("forgets everything on a new day", () => {
    const s = memory()
    writeDismissed(s, "2026-11-12", new Set(["result:5"]))
    expect(readDismissed(s, "2026-11-13").size).toBe(0)
  })

  it("survives missing, corrupt or throwing storage", () => {
    expect(readDismissed(null, "d").size).toBe(0)
    const s = memory()
    s.setItem(DISMISS_KEY, "{not json")
    expect(readDismissed(s, "d").size).toBe(0)
    const throwing = { getItem: () => { throw new Error("blocked") }, setItem: () => { throw new Error("blocked") } }
    expect(readDismissed(throwing, "d").size).toBe(0)
    expect(() => writeDismissed(throwing, "d", new Set(["x"]))).not.toThrow()
  })
})

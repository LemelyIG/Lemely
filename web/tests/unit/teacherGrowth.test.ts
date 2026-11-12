import { describe, expect, it } from "vitest"
import { growthModel, ROSTER_NUDGE } from "@/portals/teacher/home/growth"

const cls = (o: Partial<Parameters<typeof growthModel>[0][number]> = {}) => ({
  id: "c1", label: "Y11 Physics", studentCount: 28, joinCode: "ABC123", average: null, topWeakness: null, delta: null, ...o,
})
const ov = (paperCount = 0, atRisk: unknown[] = []) => ({ paperCount, atRisk: atRisk as never[] })
const full = (id: string) => cls({ id, average: 70, topWeakness: "Forces", delta: 2 })

describe("growthModel", () => {
  it("asks for a class first when there are none", () => {
    const g = growthModel([], ov())
    expect(g.next?.kind).toBe("create")
    expect(g.next?.to).toBe("/teacher/first-class")
    expect(g.complete).toBe(false)
  })

  it("nudges sharing the join code under the roster nudge and says how many joined", () => {
    const g = growthModel([cls({ studentCount: 2 })], ov())
    expect(g.next).toMatchObject({ kind: "share", code: "ABC123" })
    expect(g.next?.body).toContain("2 students have joined")
    expect(growthModel([cls({ studentCount: 1 })], ov()).next?.body).toContain("1 student has joined")
  })

  it("stops nudging at the threshold, and never without a join code", () => {
    expect(growthModel([cls({ studentCount: ROSTER_NUDGE })], ov()).next?.kind).toBe("upload")
    expect(growthModel([cls({ studentCount: 2, joinCode: null })], ov()).next?.kind).toBe("upload")
  })

  it("asks for a second paper once papers exist but no trend can be computed", () => {
    expect(growthModel([cls()], ov(1)).next?.kind).toBe("second")
    expect(growthModel([cls({ average: 60 })], ov(3)).next?.kind).toBe("second")
  })

  it("suggests another class when only one remains to add and trends exist", () => {
    expect(growthModel([full("c1")], ov(4)).next?.kind).toBe("class")
  })

  it("orders the unlocks and derives done from real fields only", () => {
    const g = growthModel([cls({ average: 60, topWeakness: "Forces" })], ov(1))
    expect(g.unlocks.map((u) => [u.key, u.done])).toEqual([["average", true], ["weakest", true], ["trend", false], ["atrisk", false]])
    const t = growthModel([cls({ delta: 0 })], ov(2))
    expect(t.unlocks.find((u) => u.key === "trend")?.done).toBe(true)
    expect(t.unlocks.find((u) => u.key === "atrisk")?.done).toBe(true)
  })

  it("is complete only when every unlock is done and nothing is left to suggest", () => {
    const done = growthModel([full("c1"), full("c2")], ov(40))
    expect(done.complete).toBe(true)
    expect(done.next).toBeNull()
    // Everything unlocked but a thin roster still has a next action.
    expect(growthModel([full("c1"), cls({ ...full("c2"), studentCount: 3 })], ov(40)).complete).toBe(false)
    // No next action but a locked unlock is not complete either.
    expect(growthModel([{ ...full("c1"), topWeakness: null }, { ...full("c2"), topWeakness: null }], ov(40))).toMatchObject({ next: null, complete: false })
  })
})

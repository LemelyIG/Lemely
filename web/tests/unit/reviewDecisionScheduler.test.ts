import { describe, expect, it } from "vitest"
import type { ReviewDecision } from "@/lib/reviewApi"
import { createDecisionScheduler } from "@/portals/teacher/screens/review/decisionScheduler"

const a: ReviewDecision = { kind: "resolve", itemId: "a", label: "Q1", changed: false, body: {} }
const b: ReviewDecision = { kind: "dismiss", itemId: "b", label: "Q2", body: {} }

/** A manual clock: timers fire only when `advance` passes their due time. */
function harness() {
  let now = 0
  let nextId = 1
  const timers = new Map<number, { due: number; fn: () => void }>()
  const sent: Array<{ id: string; keepalive: boolean; at: number }> = []
  const scheduler = createDecisionScheduler({
    fire: (d, keepalive) => sent.push({ id: d.itemId, keepalive, at: now }),
    setTimeout: (fn, ms) => {
      const id = nextId++
      timers.set(id, { due: now + ms, fn })
      return id
    },
    clearTimeout: (h) => void timers.delete(h as number),
  })
  const advance = (ms: number) => {
    now += ms
    for (const [id, t] of [...timers]) {
      if (t.due <= now) {
        timers.delete(id)
        t.fn()
      }
    }
  }
  return { scheduler, sent, advance }
}

describe("createDecisionScheduler undo hold", () => {
  it("sends nothing before 5000ms and sends at 5000ms", () => {
    const { scheduler, sent, advance } = harness()
    scheduler.decide(a)
    expect(sent).toEqual([])
    advance(4999)
    expect(sent).toEqual([])
    advance(1)
    expect(sent).toEqual([{ id: "a", keepalive: false, at: 5000 }])
  })

  it("a second decision sends the first immediately", () => {
    const { scheduler, sent, advance } = harness()
    scheduler.decide(a)
    advance(2000)
    scheduler.decide(b)
    expect(sent).toEqual([{ id: "a", keepalive: false, at: 2000 }])
    advance(4999)
    expect(sent).toHaveLength(1)
    advance(1)
    expect(sent.map((s) => s.id)).toEqual(["a", "b"])
  })

  it("undo within the window cancels the send", () => {
    const { scheduler, sent, advance } = harness()
    scheduler.decide(a)
    advance(3000)
    expect(scheduler.undo()).toBe(true)
    advance(10000)
    expect(sent).toEqual([])
    expect(scheduler.undo()).toBe(false)
  })

  it("flush (pagehide or unmount) sends now with keepalive and leaves no second send", () => {
    const { scheduler, sent, advance } = harness()
    scheduler.decide(a)
    advance(1000)
    scheduler.flush(true)
    expect(sent).toEqual([{ id: "a", keepalive: true, at: 1000 }])
    advance(10000)
    expect(sent).toHaveLength(1)
  })
})

import { describe, expect, it } from "vitest"
import { DRAG_THRESHOLD, dragScrollLeft, isDragMove } from "@/portals/teacher/home/useDragScroll"
import {
  dragScrollStep,
  IDLE,
  type DragInput,
  type DragState,
} from "@/portals/teacher/home/dragScrollMachine"

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

const down = (over: Partial<Extract<DragInput, { type: "down" }>> = {}): DragInput => ({
  type: "down",
  pointerType: "mouse",
  button: 0,
  pointerId: 1,
  clientX: 100,
  offsetY: 40,
  clientHeight: 120,
  scrollLeft: 300,
  ...over,
})
const move = (clientX: number, buttons = 1, pointerId = 1): DragInput => ({
  type: "move",
  pointerId,
  clientX,
  buttons,
})

function run(inputs: DragInput[], from: DragState = IDLE) {
  let state = from
  const effects = inputs.map((input) => {
    const step = dragScrollStep(state, input)
    state = step.state
    return step.effects
  })
  return { state, effects }
}

describe("dragScrollStep", () => {
  it("starts only on a primary-button mouse press", () => {
    for (const input of [down({ pointerType: "touch" }), down({ pointerType: "pen" }), down({ button: 2 })]) {
      expect(dragScrollStep(IDLE, input).state.phase).toBe("idle")
    }
    expect(dragScrollStep(IDLE, down()).state.phase).toBe("pressed")
  })

  it("leaves a press on the scrollbar strip below clientHeight to the scrollbar", () => {
    expect(dragScrollStep(IDLE, down({ offsetY: 120 })).state.phase).toBe("idle")
    expect(dragScrollStep(IDLE, down({ offsetY: 131 })).state.phase).toBe("idle")
    expect(dragScrollStep(IDLE, down({ offsetY: 119 })).state.phase).toBe("pressed")
  })

  it("captures the pointer only once travel passes the threshold", () => {
    const small = run([down(), move(100 + DRAG_THRESHOLD)])
    expect(small.state.phase).toBe("pressed")
    expect(small.effects[1]).toEqual({})

    const big = run([down(), move(100 - DRAG_THRESHOLD - 1)])
    expect(big.state.phase).toBe("dragging")
    expect(big.effects[1]).toEqual({ capture: 1, dragVisual: "start", scrollLeft: 306 })
  })

  it("scrolls opposite the pointer while dragging", () => {
    const { effects } = run([down(), move(120), move(60)])
    expect(effects[2]).toEqual({ scrollLeft: 340 })
  })

  it("ignores moves from another pointer", () => {
    const { state, effects } = run([down(), move(160, 1, 2)])
    expect(state.phase).toBe("pressed")
    expect(effects[1]).toEqual({})
  })

  it("ends the press when a move reports no buttons held", () => {
    const pressed = run([down(), move(102, 0)])
    expect(pressed.state).toEqual({ phase: "idle", swallowClick: false })
    expect(pressed.effects[1]).toEqual({ release: 1 })

    const dragged = run([down(), move(140), move(150, 0)])
    expect(dragged.state).toEqual({ phase: "idle", swallowClick: true })
    expect(dragged.effects[2]).toEqual({ release: 1, dragVisual: "end", scheduleClickReset: true })
  })

  it("swallows exactly the click that follows a drag", () => {
    const { state, effects } = run([down(), move(140), { type: "end", pointerId: 1 }, { type: "click" }, { type: "click" }])
    expect(effects[3]).toEqual({ preventClick: true })
    expect(effects[4]).toEqual({})
    expect(state.swallowClick).toBe(false)
  })

  it("lets a plain click through", () => {
    const { effects } = run([down(), move(103), { type: "end", pointerId: 1 }, { type: "click" }])
    expect(effects[3]).toEqual({})
  })

  it("forgets the swallow flag when no click arrives", () => {
    const { effects } = run([
      down(),
      move(140),
      { type: "end", pointerId: 1 },
      { type: "clickWindowElapsed" },
      { type: "click" },
    ])
    expect(effects[4]).toEqual({})
  })
})

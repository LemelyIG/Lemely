/*
 * The decisions behind `useDragScroll`, as a pure state machine.
 *
 * The hook only translates DOM events into `DragInput`s, feeds them through
 * `dragScrollStep`, and applies the returned effects. Everything that decides
 * whether a press is a drag (mouse only, primary button, not on the
 * scrollbar, past the threshold, still held) lives here, where a Node unit
 * test reaches it without a DOM.
 */

/** Pointer travel (px) after which a press counts as a drag, not a click. */
export const DRAG_THRESHOLD = 5

export function isDragMove(startX: number, x: number, threshold = DRAG_THRESHOLD): boolean {
  return Math.abs(x - startX) > threshold
}

/** The scrollLeft a drag that started at `startX` / `startScroll` produces at pointer `x`. */
export function dragScrollLeft(startScroll: number, startX: number, x: number): number {
  return startScroll - (x - startX)
}

interface Press {
  pointerId: number
  startX: number
  startScroll: number
}

export type DragState =
  | { phase: "idle"; swallowClick: boolean }
  | ({ phase: "pressed"; swallowClick: boolean } & Press)
  | ({ phase: "dragging"; swallowClick: boolean } & Press)

export const IDLE: DragState = { phase: "idle", swallowClick: false }

export type DragInput =
  | {
      type: "down"
      pointerType: string
      button: number
      pointerId: number
      clientX: number
      /** Pointer y relative to the scroller's padding box top. */
      offsetY: number
      /** The scroller's `clientHeight`: below it is the horizontal scrollbar. */
      clientHeight: number
      scrollLeft: number
    }
  | { type: "move"; pointerId: number; clientX: number; buttons: number }
  | { type: "end"; pointerId: number }
  | { type: "click" }
  /** The tick after a drag ended: a click that never arrived is forgotten. */
  | { type: "clickWindowElapsed" }

export interface DragEffects {
  capture?: number
  release?: number
  scrollLeft?: number
  dragVisual?: "start" | "end"
  preventClick?: boolean
  scheduleClickReset?: boolean
}

export interface DragStep {
  state: DragState
  effects: DragEffects
}

function finish(state: DragState & Press): DragStep {
  if (state.phase === "dragging") {
    return {
      state: { phase: "idle", swallowClick: true },
      effects: { release: state.pointerId, dragVisual: "end", scheduleClickReset: true },
    }
  }
  return { state: { phase: "idle", swallowClick: state.swallowClick }, effects: { release: state.pointerId } }
}

export function dragScrollStep(state: DragState, event: DragInput): DragStep {
  switch (event.type) {
    case "down": {
      if (event.pointerType !== "mouse" || event.button !== 0) return { state, effects: {} }
      // A press on the native horizontal scrollbar belongs to the scrollbar.
      if (event.offsetY >= event.clientHeight) return { state, effects: {} }
      return {
        state: {
          phase: "pressed",
          swallowClick: state.swallowClick,
          pointerId: event.pointerId,
          startX: event.clientX,
          startScroll: event.scrollLeft,
        },
        effects: {},
      }
    }
    case "move": {
      if (state.phase === "idle" || event.pointerId !== state.pointerId) return { state, effects: {} }
      // The button came up somewhere we never heard about (outside the window).
      if (event.buttons === 0) return finish(state)
      if (state.phase === "pressed") {
        if (!isDragMove(state.startX, event.clientX)) return { state, effects: {} }
        return {
          state: { ...state, phase: "dragging" },
          effects: {
            capture: state.pointerId,
            dragVisual: "start",
            scrollLeft: dragScrollLeft(state.startScroll, state.startX, event.clientX),
          },
        }
      }
      return {
        state,
        effects: { scrollLeft: dragScrollLeft(state.startScroll, state.startX, event.clientX) },
      }
    }
    case "end": {
      if (state.phase === "idle" || event.pointerId !== state.pointerId) return { state, effects: {} }
      return finish(state)
    }
    case "click": {
      if (!state.swallowClick) return { state, effects: {} }
      return { state: { ...state, swallowClick: false }, effects: { preventClick: true } }
    }
    case "clickWindowElapsed":
      return { state: { ...state, swallowClick: false }, effects: {} }
  }
}

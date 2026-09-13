import { useRef } from "react"
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from "react"
import { longPressDecision } from "./longPressMath"

/*
 * Task 5 (B4a) · long-press for a row's secondary-actions menu (question,
 * notification, deck — wired in Task 6). Every transient pointer value
 * (start position, start time, the pending timer) lives in one ref, same
 * rule as `useDragGesture.ts`'s own header comment: a hold's `pointermove`
 * can fire many times before the hold completes, and re-rendering the row on
 * each one is exactly what `rerender-use-ref-transient-values` exists to
 * prevent. There is nothing here for `useState` to usefully hold — the hook
 * returns stable handler functions, not a piece of UI state — so it holds
 * none at all.
 */

const INTERACTIVE_SELECTOR = "button, a, input, textarea, select, [role=radio], [role=checkbox]"

export interface UseLongPressHandlers {
  onLongPress: (event: PointerEvent) => void
  /** Hold duration in ms before `onLongPress` fires. Default 500. */
  holdMs?: number
  /** Movement in CSS pixels from the start position that cancels the press
   * (a drag or scroll, not a hold). Default 10. */
  moveTolerance?: number
}

export interface UseLongPressResult {
  onPointerDown: (event: ReactPointerEvent) => void
  onPointerMove: (event: ReactPointerEvent) => void
  onPointerUp: (event: ReactPointerEvent) => void
  onPointerCancel: (event: ReactPointerEvent) => void
  onContextMenu: (event: ReactMouseEvent) => void
}

interface PressState {
  startX: number
  startY: number
  startedAt: number
  timer: ReturnType<typeof setTimeout>
  fired: boolean
}

export function useLongPress(handlers: UseLongPressHandlers): UseLongPressResult {
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers
  const stateRef = useRef<PressState | null>(null)

  function clearPress() {
    if (stateRef.current) clearTimeout(stateRef.current.timer)
    stateRef.current = null
  }

  function onPointerDown(event: ReactPointerEvent) {
    const target = event.target
    const startedOnInteractive = target instanceof Element && target.closest(INTERACTIVE_SELECTOR) !== null
    if (startedOnInteractive) return

    const nativeEvent = event.nativeEvent
    const holdMs = handlersRef.current.holdMs ?? 500
    const timer = setTimeout(() => {
      const state = stateRef.current
      if (!state) return
      state.fired = true
      handlersRef.current.onLongPress(nativeEvent)
    }, holdMs)

    stateRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      startedAt: Date.now(),
      timer,
      fired: false,
    }
  }

  function onPointerMove(event: ReactPointerEvent) {
    const state = stateRef.current
    if (!state || state.fired) return
    const movedPx = Math.hypot(event.clientX - state.startX, event.clientY - state.startY)
    const decision = longPressDecision({
      elapsedMs: Date.now() - state.startedAt,
      movedPx,
      holdMs: handlersRef.current.holdMs ?? 500,
      moveTolerance: handlersRef.current.moveTolerance ?? 10,
      startedOnInteractive: false,
    })
    if (decision === "cancel") clearPress()
  }

  function onPointerUp() {
    clearPress()
  }

  function onPointerCancel() {
    clearPress()
  }

  function onContextMenu(event: ReactMouseEvent) {
    if (stateRef.current) event.preventDefault()
  }

  return { onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onContextMenu }
}

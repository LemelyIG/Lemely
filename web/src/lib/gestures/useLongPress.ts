import { useEffect, useRef } from "react"
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from "react"
import { longPressDecision, shouldStartLongPress, shouldSuppressContextMenu } from "./longPressMath"

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
 *
 * Long-press is always *additive*. Every menu it opens is reachable some
 * other way (a visible button on the row, or the row's own "More actions"
 * trigger): a pointer gesture is the only way to reach an action would be a
 * WCAG 2.1.1 / 2.5.1 failure, and a hold cannot be performed with a
 * keyboard at all.
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
  /** Swallows the `click` the browser synthesises straight after a hold that
   * fired. Without it the menu opened by the press is immediately toggled
   * shut again by the trigger's own click handler. */
  onClickCapture: (event: ReactMouseEvent) => void
}

interface PressState {
  startX: number
  startY: number
  startedAt: number
  pointerType: string
  timer: ReturnType<typeof setTimeout>
  fired: boolean
}

export function useLongPress(handlers: UseLongPressHandlers): UseLongPressResult {
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers
  const stateRef = useRef<PressState | null>(null)
  const suppressClickRef = useRef(false)

  function clearPress() {
    if (stateRef.current) clearTimeout(stateRef.current.timer)
    stateRef.current = null
  }

  // Without this the hold timer outlives the component and fires
  // `onLongPress` — a `setState` on a row that no longer exists — whenever a
  // press is interrupted by a navigation or a list re-render.
  useEffect(() => () => clearPress(), [])

  function onPointerDown(event: ReactPointerEvent) {
    suppressClickRef.current = false
    const target = event.target
    const startedOnInteractive = target instanceof Element && target.closest(INTERACTIVE_SELECTOR) !== null
    if (!shouldStartLongPress({ button: event.button, startedOnInteractive })) return

    const nativeEvent = event.nativeEvent
    const holdMs = handlersRef.current.holdMs ?? 500
    const timer = setTimeout(() => {
      const state = stateRef.current
      if (!state) return
      state.fired = true
      suppressClickRef.current = true
      handlersRef.current.onLongPress(nativeEvent)
    }, holdMs)

    stateRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      startedAt: Date.now(),
      pointerType: event.pointerType,
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
    const state = stateRef.current
    if (!state) return
    // A mouse right-click keeps the browser's own menu: this hook offers
    // nothing in its place, and suppressing it left the user with neither.
    if (shouldSuppressContextMenu(state.pointerType, true)) event.preventDefault()
  }

  function onClickCapture(event: ReactMouseEvent) {
    if (!suppressClickRef.current) return
    suppressClickRef.current = false
    event.preventDefault()
    event.stopPropagation()
  }

  return { onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onContextMenu, onClickCapture }
}

import { useEffect, useRef, type RefObject } from "react"
import { shouldCommitDrag, type DragAxis } from "./dragMath"

/*
 * Packet B3 (Task 4) · the single source of truth for a one-finger drag
 * gesture, shared by every consumer that needs one: `EdgeSwipeBack` here,
 * `NavDrawer`'s drag-dismiss and `FlashcardReview`/`QuizTaker`'s swipes in
 * B4, `usePullToRefresh` in B4 too.
 *
 * Pointer Events (not touch/mouse separately) so mouse-drag testing and
 * stylus input both work for free. Every coordinate lives in a ref, never
 * `useState` — a drag fires many times a frame, and re-rendering the
 * component on each one is exactly the class of thing `react-best-practices`
 * (`rerender-use-ref-transient-values`) exists to prevent. The one thing
 * this hook writes to the DOM directly, imperatively, is `transformTarget`'s
 * (or `ref`'s own) `style.transform` — same reasoning, one frame ahead of
 * whatever `onProgress` does with the same numbers.
 */

export interface DragGestureOptions {
  axis: DragAxis
  onCommit: (dx: number, dy: number) => void
  onProgress?: (dx: number, dy: number) => void
  onCancel?: () => void
  /** Same units as `dragMath.ts`'s `shouldCommitDrag`. Default 10. */
  commitThreshold?: number
  /** Default true. `false` detaches the listener entirely (not merely a
   * no-op check inside it) — `EdgeSwipeBack` uses this to install nothing at
   * all in a browser tab. */
  enabled?: boolean
  /** Runs on `pointerdown`; returning `false` lets the event fall through
   * (scroll, native selection, a nested interactive control) instead of
   * starting a drag. */
  startFilter?: (event: PointerEvent) => boolean
  /** Where the imperative `transform` lands while dragging. Defaults to
   * `ref` itself — a drawer/card that IS its own transform target — but a
   * gesture surface (a document-wide edge-swipe listener, say) usually wants
   * a different element to actually move. */
  transformTarget?: RefObject<HTMLElement | null>
}

interface DragState {
  pointerId: number
  startX: number
  startY: number
}

export function useDragGesture(ref: RefObject<HTMLElement | null>, options: DragGestureOptions): void {
  const optionsRef = useRef(options)
  optionsRef.current = options
  const stateRef = useRef<DragState | null>(null)

  useEffect(() => {
    const el = ref.current
    if (!el || options.enabled === false) return

    function target(): HTMLElement {
      return optionsRef.current.transformTarget?.current ?? el!
    }

    function clearTransform() {
      const t = target()
      t.style.transform = ""
    }

    function springBack() {
      const t = target()
      t.style.transition = "transform var(--dur-base) var(--ease-spring)"
      t.style.transform = ""
      const onTransitionEnd = () => {
        t.style.transition = ""
        t.removeEventListener("transitionend", onTransitionEnd)
      }
      t.addEventListener("transitionend", onTransitionEnd)
    }

    function detachDragListeners() {
      el!.removeEventListener("pointermove", onPointerMove)
      el!.removeEventListener("pointerup", onPointerUp)
      el!.removeEventListener("pointercancel", onPointerCancel)
    }

    function onPointerMove(event: PointerEvent) {
      const state = stateRef.current
      if (!state || event.pointerId !== state.pointerId) return
      const dx = event.clientX - state.startX
      const dy = event.clientY - state.startY
      const t = target()
      t.style.transform = optionsRef.current.axis === "x" ? `translateX(${dx}px)` : `translateY(${dy}px)`
      optionsRef.current.onProgress?.(dx, dy)
    }

    function endDrag(event: PointerEvent) {
      const state = stateRef.current
      if (!state || event.pointerId !== state.pointerId) return
      stateRef.current = null
      detachDragListeners()
      try {
        el!.releasePointerCapture(event.pointerId)
      } catch {
        // Capture may already have been released (e.g. by the browser on a
        // cancelled gesture) — releasing an already-released pointer throws
        // in some engines and there is nothing further to clean up either way.
      }

      const dx = event.clientX - state.startX
      const dy = event.clientY - state.startY
      const threshold = optionsRef.current.commitThreshold ?? 10
      if (shouldCommitDrag(dx, dy, optionsRef.current.axis, threshold)) {
        clearTransform()
        optionsRef.current.onCommit(dx, dy)
      } else {
        springBack()
        optionsRef.current.onCancel?.()
      }
    }

    function onPointerUp(event: PointerEvent) {
      endDrag(event)
    }

    function onPointerCancel(event: PointerEvent) {
      const state = stateRef.current
      if (!state || event.pointerId !== state.pointerId) return
      stateRef.current = null
      detachDragListeners()
      springBack()
      optionsRef.current.onCancel?.()
    }

    function onPointerDown(event: PointerEvent) {
      if (optionsRef.current.startFilter && !optionsRef.current.startFilter(event)) return
      stateRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY }
      el!.setPointerCapture(event.pointerId)
      el!.addEventListener("pointermove", onPointerMove)
      el!.addEventListener("pointerup", onPointerUp)
      el!.addEventListener("pointercancel", onPointerCancel)
    }

    el.addEventListener("pointerdown", onPointerDown)
    return () => {
      el.removeEventListener("pointerdown", onPointerDown)
      detachDragListeners()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, options.enabled])
}

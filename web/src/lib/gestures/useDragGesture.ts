import { useEffect, useRef, type RefObject } from "react"
import { clampDelta, shouldCommitDrag, type DragAxis, type DragClamp } from "./dragMath"

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
  /** Restricts the direction the imperative transform may move in, without
   * touching the raw deltas `onProgress`/`onCommit` receive. Default
   * `"none"`. Pull-to-refresh uses `"positive"`: its surface may only be
   * pushed down, never pulled up out of the viewport. */
  transformClamp?: DragClamp
  /** Set as `touch-action` on `ref` for as long as the gesture is attached,
   * and restored on cleanup. A horizontal-drag surface wants `"pan-y"`, so
   * the browser keeps vertical scrolling but stops claiming the horizontal
   * direction before this hook has seen enough movement to commit. Left
   * unset by default — a *vertical* drag surface must NOT declare `pan-x`,
   * which would stop the page scrolling through it altogether. */
  touchAction?: string
}

/** How long to wait for `springBack`'s `transitionend` before clearing the
 * transition anyway. Longer than `--dur-base` (320ms) with room for a slow
 * frame; the listener normally wins this race. */
const SPRING_FALLBACK_MS = 600

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

    let springTimer: ReturnType<typeof setTimeout> | null = null

    function springBack() {
      const t = target()
      if (springTimer !== null) {
        clearTimeout(springTimer)
        springTimer = null
      }
      // A tap that never moved the target wrote no transform, so setting it
      // back to "" changes nothing and no `transitionend` will ever fire.
      // Waiting for one left `style.transition` set on the element forever.
      if (!t.style.transform) {
        t.style.transition = ""
        return
      }
      t.style.transition = "transform var(--dur-base) var(--ease-spring)"
      t.style.transform = ""
      const finish = () => {
        if (springTimer !== null) {
          clearTimeout(springTimer)
          springTimer = null
        }
        t.style.transition = ""
        t.removeEventListener("transitionend", finish)
      }
      t.addEventListener("transitionend", finish, { once: true })
      springTimer = setTimeout(finish, SPRING_FALLBACK_MS)
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
      const axis = optionsRef.current.axis
      const moved = clampDelta(axis === "x" ? dx : dy, optionsRef.current.transformClamp)
      // A clamped-away drag writes no transform at all rather than
      // `translate(0)`: a transformed element becomes the containing block
      // for its `position: fixed` descendants, and paying that for a drag
      // that visibly moves nothing is how C2 shifted the bottom nav.
      t.style.transform = moved === 0 ? "" : axis === "x" ? `translateX(${moved}px)` : `translateY(${moved}px)`
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
      // A second finger landing mid-drag would otherwise overwrite the
      // in-flight state and strand the first pointer's capture.
      if (stateRef.current !== null) return
      if (optionsRef.current.startFilter && !optionsRef.current.startFilter(event)) return
      stateRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY }
      el!.setPointerCapture(event.pointerId)
      el!.addEventListener("pointermove", onPointerMove)
      el!.addEventListener("pointerup", onPointerUp)
      el!.addEventListener("pointercancel", onPointerCancel)
    }

    /*
     * Everything this hook wrote imperatively, put back. Detaching the
     * listeners alone was H5: `QuizTaker` recomputes `enabled` on a 1s tick
     * (the last-60-seconds lock), so a drag in progress when that boundary
     * crossed left the question card permanently offset by its last
     * `translateX`, still holding pointer capture and swallowing every tap
     * that landed on it. Same shape on `FlashcardReview` and `NavDrawer`.
     */
    function abortDrag() {
      if (springTimer !== null) {
        clearTimeout(springTimer)
        springTimer = null
      }
      const state = stateRef.current
      stateRef.current = null
      detachDragListeners()
      if (state !== null) {
        try {
          el!.releasePointerCapture(state.pointerId)
        } catch {
          // Already released — see `endDrag`'s own note.
        }
      }
      const t = target()
      t.style.transform = ""
      t.style.transition = ""
    }

    const previousTouchAction = el.style.touchAction
    if (options.touchAction !== undefined) el.style.touchAction = options.touchAction

    el.addEventListener("pointerdown", onPointerDown)
    return () => {
      el.removeEventListener("pointerdown", onPointerDown)
      if (options.touchAction !== undefined) el.style.touchAction = previousTouchAction
      abortDrag()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, options.enabled, options.touchAction])
}

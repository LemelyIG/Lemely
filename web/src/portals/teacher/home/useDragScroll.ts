import { useEffect, type RefObject } from "react"
import { dragScrollStep, IDLE, type DragEffects, type DragInput, type DragState } from "./dragScrollMachine"

export { DRAG_THRESHOLD, dragScrollLeft, isDragMove } from "./dragScrollMachine"

/**
 * Mouse drag-to-scroll for a horizontal scroller. Touch and keyboard keep
 * their native scrolling: only `pointerType === "mouse"` with the primary
 * button is handled, and a press on the native scrollbar is left to it. The
 * pointer is captured only once the press becomes a drag, so a plain click
 * still reaches the link under it. Pass `enabled` false while the scroller is
 * not rendered. Every decision is `dragScrollStep`'s (`dragScrollMachine.ts`);
 * this hook only wires DOM events to it and applies its effects.
 */
export function useDragScroll(ref: RefObject<HTMLElement | null>, enabled = true): void {
  useEffect(() => {
    const el = ref.current
    if (!el || !enabled) return

    let state: DragState = IDLE

    const apply = (effects: DragEffects, event?: Event) => {
      if (effects.capture !== undefined) el.setPointerCapture(effects.capture)
      if (effects.dragVisual === "start") {
        el.dataset.dragging = ""
        el.style.scrollSnapType = "none"
      }
      if (effects.scrollLeft !== undefined) el.scrollLeft = effects.scrollLeft
      if (effects.dragVisual === "end") {
        delete el.dataset.dragging
        el.style.scrollSnapType = ""
      }
      if (effects.release !== undefined && el.hasPointerCapture?.(effects.release)) {
        el.releasePointerCapture(effects.release)
      }
      if (effects.scheduleClickReset) {
        // A drag that ends over a link fires a click; if none arrives, forget the flag.
        window.setTimeout(() => send({ type: "clickWindowElapsed" }), 0)
      }
      if (effects.preventClick && event) {
        event.preventDefault()
        event.stopPropagation()
      }
    }
    const send = (input: DragInput, event?: Event) => {
      const step = dragScrollStep(state, input)
      state = step.state
      apply(step.effects, event)
    }

    const onDown = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect()
      send({
        type: "down",
        pointerType: e.pointerType,
        button: e.button,
        pointerId: e.pointerId,
        clientX: e.clientX,
        offsetY: e.clientY - rect.top - el.clientTop,
        clientHeight: el.clientHeight,
        scrollLeft: el.scrollLeft,
      })
    }
    const onMove = (e: PointerEvent) =>
      send({ type: "move", pointerId: e.pointerId, clientX: e.clientX, buttons: e.buttons })
    const onEnd = (e: PointerEvent) => send({ type: "end", pointerId: e.pointerId })
    const onClick = (e: MouseEvent) => send({ type: "click" }, e)
    const onDragStart = (e: Event) => e.preventDefault()

    el.addEventListener("pointerdown", onDown)
    el.addEventListener("pointermove", onMove)
    el.addEventListener("pointerup", onEnd)
    el.addEventListener("pointercancel", onEnd)
    el.addEventListener("lostpointercapture", onEnd)
    el.addEventListener("click", onClick, true)
    el.addEventListener("dragstart", onDragStart)
    return () => {
      el.removeEventListener("pointerdown", onDown)
      el.removeEventListener("pointermove", onMove)
      el.removeEventListener("pointerup", onEnd)
      el.removeEventListener("pointercancel", onEnd)
      el.removeEventListener("lostpointercapture", onEnd)
      el.removeEventListener("click", onClick, true)
      el.removeEventListener("dragstart", onDragStart)
      delete el.dataset.dragging
      el.style.scrollSnapType = ""
    }
  }, [ref, enabled])
}

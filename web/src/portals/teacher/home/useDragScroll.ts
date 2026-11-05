import { useEffect, type RefObject } from "react"

/** Pointer travel (px) after which a press counts as a drag, not a click. */
export const DRAG_THRESHOLD = 5

export function isDragMove(startX: number, x: number, threshold = DRAG_THRESHOLD): boolean {
  return Math.abs(x - startX) > threshold
}

/** The scrollLeft a drag that started at `startX` / `startScroll` produces at pointer `x`. */
export function dragScrollLeft(startScroll: number, startX: number, x: number): number {
  return startScroll - (x - startX)
}

/**
 * Mouse drag-to-scroll for a horizontal scroller. Touch and keyboard keep
 * their native scrolling: only `pointerType === "mouse"` with the primary
 * button is handled. The pointer is captured only once the press becomes a
 * drag, so a plain click still reaches the link under it. Pass `enabled`
 * false while the scroller is not rendered.
 */
export function useDragScroll(ref: RefObject<HTMLElement | null>, enabled = true): void {
  useEffect(() => {
    const el = ref.current
    if (!el || !enabled) return

    let pointerId: number | null = null
    let startX = 0
    let startScroll = 0
    let dragging = false
    let swallowClick = false

    const end = () => {
      if (pointerId === null) return
      const id = pointerId
      pointerId = null
      if (dragging) {
        dragging = false
        swallowClick = true
        // A drag that ends over a link fires a click; if none arrives, forget the flag.
        window.setTimeout(() => { swallowClick = false }, 0)
        delete el.dataset.dragging
        el.style.scrollSnapType = ""
      }
      if (el.hasPointerCapture?.(id)) el.releasePointerCapture(id)
    }

    const onDown = (e: PointerEvent) => {
      if (e.pointerType !== "mouse" || e.button !== 0) return
      pointerId = e.pointerId
      startX = e.clientX
      startScroll = el.scrollLeft
      dragging = false
    }
    const onMove = (e: PointerEvent) => {
      if (e.pointerId !== pointerId) return
      if (!dragging) {
        if (!isDragMove(startX, e.clientX)) return
        dragging = true
        el.dataset.dragging = ""
        el.style.scrollSnapType = "none"
        el.setPointerCapture(e.pointerId)
      }
      el.scrollLeft = dragScrollLeft(startScroll, startX, e.clientX)
    }
    const onClick = (e: MouseEvent) => {
      if (!swallowClick) return
      swallowClick = false
      e.preventDefault()
      e.stopPropagation()
    }
    const onDragStart = (e: DragEvent) => e.preventDefault()

    el.addEventListener("pointerdown", onDown)
    el.addEventListener("pointermove", onMove)
    el.addEventListener("pointerup", end)
    el.addEventListener("pointercancel", end)
    el.addEventListener("lostpointercapture", end)
    el.addEventListener("click", onClick, true)
    el.addEventListener("dragstart", onDragStart)
    return () => {
      el.removeEventListener("pointerdown", onDown)
      el.removeEventListener("pointermove", onMove)
      el.removeEventListener("pointerup", end)
      el.removeEventListener("pointercancel", end)
      el.removeEventListener("lostpointercapture", end)
      el.removeEventListener("click", onClick, true)
      el.removeEventListener("dragstart", onDragStart)
      delete el.dataset.dragging
      el.style.scrollSnapType = ""
    }
  }, [ref, enabled])
}

import { useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from "react"

/**
 * Bounds an element to the rest of the viewport, so a screen can own its scrolling (the shell's `main` never
 * scrolls, which is why a `sticky` footer inside it never engages). The element's own top edge and the shell
 * `main`'s bottom padding are measured, not assumed, because a banner or a breadcrumb row moves the first and
 * the padding changes with the breakpoint. The negative bottom margin gives the padding back so the element
 * reaches the bottom edge and the document is exactly one viewport tall. `keepPadding` (phone) stops above the
 * padding instead, because there it clears the fixed tab bar.
 */
export function useFillViewport<T extends HTMLElement>(active: boolean, keepPadding = false): { ref: RefObject<T | null>; style: CSSProperties | undefined } {
  const ref = useRef<T | null>(null)
  const [fit, setFit] = useState<{ top: number; pad: number } | null>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!active || !el) return
    const parent = el.closest("main") ?? el.parentElement
    // Layout offsets, not getBoundingClientRect: the screen's entrance animation transforms an ancestor.
    const offsetTop = () => {
      let top = 0
      for (let n: HTMLElement | null = el; n; n = n.offsetParent as HTMLElement | null) top += n.offsetTop
      return top
    }
    const measure = () => {
      const top = Math.round(offsetTop())
      // keepPadding: clear whichever is taller, the padding or the visible tab bar (it is also a fixed overlay).
      const bar = keepPadding ? document.querySelector<HTMLElement>(".lm-native-tabbar") : null
      const barH = bar && bar.getClientRects().length ? Math.round(bar.getBoundingClientRect().height) : 0
      const pad0 = parent ? Math.round(parseFloat(getComputedStyle(parent).paddingBottom) || 0) : 0
      const pad = keepPadding ? Math.max(pad0, barH) : pad0
      setFit((prev) => (prev && prev.top === top && prev.pad === pad ? prev : { top, pad }))
    }
    measure()
    window.addEventListener("resize", measure)
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure)
    // Anything above the element can move its top edge: its earlier siblings, and those of each ancestor.
    for (let node: HTMLElement | null = el; node && node !== document.body; node = node.parentElement) {
      for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) ro?.observe(sib)
    }
    if (parent) ro?.observe(parent)
    return () => {
      window.removeEventListener("resize", measure)
      ro?.disconnect()
    }
  }, [active, keepPadding])
  if (!active || !fit) return { ref, style: undefined }
  // keepPadding: the padding is clearance for a fixed bottom bar, so stop above it instead of reclaiming it.
  return { ref, style: keepPadding ? { height: `calc(100dvh - ${fit.top + fit.pad}px)` } : { height: `calc(100dvh - ${fit.top}px)`, marginBottom: -fit.pad } }
}

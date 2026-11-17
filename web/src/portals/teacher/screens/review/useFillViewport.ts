import { useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from "react"

export interface FitInput {
  top: number
  parentPad: number
  barH: number
  keepPadding: boolean
}
export interface Fit {
  top: number
  /** Space to leave free at the bottom of the viewport: the fixed tab bar, and on phone at least the padding. */
  clearance: number
  pad: number
}

const px = (n: number) => (Number.isFinite(n) && n > 0 ? Math.round(n) : 0)

/** Pure measurement maths. A visible tab bar is cleared at every width; `keepPadding` also keeps the padding. */
export function computeFit({ top, parentPad, barH, keepPadding }: FitInput): Fit {
  const pad = px(parentPad)
  const bar = px(barH)
  return { top: px(top), clearance: keepPadding ? Math.max(pad, bar) : bar, pad }
}

/**
 * Height stops `clearance` above the viewport bottom. The margin settles the main padding against that, so the
 * document is exactly one viewport tall: it reclaims the padding when nothing is cleared (negative) and adds back
 * the difference when the bar is taller than the padding.
 */
export function fitStyle(fit: Fit): CSSProperties {
  return { height: `calc(100dvh - ${fit.top + fit.clearance}px)`, marginBottom: fit.clearance - fit.pad }
}

/**
 * Bounds an element to the rest of the viewport, so a screen can own its scrolling (the shell's `main` never
 * scrolls, which is why a `sticky` footer inside it never engages). The element's top edge, the shell `main`'s
 * bottom padding and the fixed tab bar are measured, not assumed, and re-measured whenever the chrome around the
 * element changes: a window resize, a banner mounting inside `main`, the large title collapsing.
 */
export function useFillViewport<T extends HTMLElement>(active: boolean, keepPadding = false): { ref: RefObject<T | null>; style: CSSProperties | undefined } {
  const ref = useRef<T | null>(null)
  const [fit, setFit] = useState<Fit | null>(null)
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
      const bar = document.querySelector<HTMLElement>(".lm-native-tabbar")
      const barH = bar && bar.getClientRects().length ? bar.getBoundingClientRect().height : 0
      const parentPad = parent ? parseFloat(getComputedStyle(parent).paddingBottom) : 0
      const next = computeFit({ top: offsetTop(), parentPad, barH, keepPadding })
      setFit((prev) => (prev && prev.top === next.top && prev.clearance === next.clearance && prev.pad === next.pad ? prev : next))
    }
    let raf = 0
    const schedule = () => {
      if (raf) return
      raf = requestAnimationFrame(() => {
        raf = 0
        measure()
      })
    }
    measure()
    window.addEventListener("resize", schedule)
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule)
    const watched = new Set<Element>()
    const watch = (n: Element | null) => {
      if (n && !watched.has(n)) {
        watched.add(n)
        ro?.observe(n)
      }
    }
    // Anything above the element can move its top edge: its earlier siblings, and those of each ancestor.
    for (let node: HTMLElement | null = el; node && node !== document.body; node = node.parentElement) {
      for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) watch(sib)
    }
    watch(parent)
    watch(document.querySelector(".lm-native-tabbar"))
    watch(document.querySelector("header"))
    // A banner mounting inside `main` is a new sibling above the screen: observe it and re-measure.
    const mo = typeof MutationObserver === "undefined" || !parent ? null : new MutationObserver(() => {
      for (let node: HTMLElement | null = el; node && node !== parent; node = node.parentElement) {
        for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) watch(sib)
      }
      schedule()
    })
    mo?.observe(parent as Node, { childList: true, subtree: true })
    return () => {
      if (raf) cancelAnimationFrame(raf)
      window.removeEventListener("resize", schedule)
      ro?.disconnect()
      mo?.disconnect()
    }
  }, [active, keepPadding])
  if (!active || !fit) return { ref, style: undefined }
  return { ref, style: fitStyle(fit) }
}

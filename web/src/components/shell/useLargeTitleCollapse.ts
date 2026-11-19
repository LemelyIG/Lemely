import { useEffect, useState, type RefObject } from "react"
import { largeTitleCollapsed } from "./largeTitle"

/**
 * Writes the large title's height to `--lm-large-title-block` (the CSS
 * scroll-driven fade reads it) and returns the collapsed state from a passive
 * scroll listener batched to one rAF. The state drives `data-collapsed`, which
 * is the whole effect on iOS < 26, under reduced motion, and in tests.
 */
export function useLargeTitleCollapse(ref: RefObject<HTMLElement | null>, enabled: boolean): boolean {
  const [collapsed, setCollapsed] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!enabled || !el) {
      setCollapsed(false)
      return
    }
    let height = el.offsetHeight
    let frame = 0
    const root = document.documentElement
    const write = () => root.style.setProperty("--lm-large-title-block", `${height}px`)
    const sync = () => {
      frame = 0
      setCollapsed(largeTitleCollapsed(window.scrollY, height))
    }
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(sync)
    }
    const resize = new ResizeObserver(() => {
      height = el.offsetHeight
      write()
      onScroll()
    })
    write()
    sync()
    resize.observe(el)
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      resize.disconnect()
      window.removeEventListener("scroll", onScroll)
      root.style.removeProperty("--lm-large-title-block")
    }
  }, [ref, enabled])
  return collapsed
}

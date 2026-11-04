import { useEffect, useState } from "react"

const GLYPHS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

/** One frame of the settle: the first `fixed` characters are real, the rest are random glyphs. */
export function settleFrame(code: string, fixed: number, rand: () => number = Math.random): string {
  return [...code].map((c, i) => (i < fixed ? c : GLYPHS[Math.floor(rand() * GLYPHS.length)])).join("")
}

/**
 * A join code that settles one character at a time, left to right, when first shown.
 * Returns the real code immediately under `prefers-reduced-motion: reduce` or when `enabled` is false.
 */
export function useSettledCode(code: string, enabled: boolean): string {
  const calm = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  const [text, setText] = useState(() => (enabled && !calm ? settleFrame(code, 0) : code))
  useEffect(() => {
    if (!enabled || calm) {
      setText(code)
      return
    }
    let frame = 0
    let raf = 0
    const tick = () => {
      const fixed = Math.floor(frame / 3)
      setText(fixed >= code.length ? code : settleFrame(code, fixed))
      frame++
      if (fixed < code.length) raf = requestAnimationFrame(tick)
    }
    tick()
    return () => cancelAnimationFrame(raf)
  }, [code, enabled, calm])
  return text
}

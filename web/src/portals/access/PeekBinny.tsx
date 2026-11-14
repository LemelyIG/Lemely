/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useRef, useState } from "react"
import { Binny, type BinnyMood } from "@/portals/marketing/Binny"
import "@/portals/marketing/brand-tokens.css"
import "./coming-soon.css"

/** Pupils follow the pointer. Off under `prefers-reduced-motion`. */
function useTrack(ref: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return
    const el = ref.current
    if (!el) return
    const on = (e: PointerEvent) => {
      const r = el.getBoundingClientRect()
      const dx = (e.clientX - (r.left + r.width / 2)) / Math.max(r.width, 360)
      const dy = (e.clientY - (r.top + r.height * 0.6)) / Math.max(r.height, 360)
      const clamp = (n: number) => Math.max(-1, Math.min(1, n))
      el.style.setProperty("--px", `${clamp(dx * 2.2) * 4}px`)
      el.style.setProperty("--py", `${clamp(dy * 2.2) * 3.5}px`)
    }
    window.addEventListener("pointermove", on)
    window.addEventListener("pointerdown", on)
    return () => {
      window.removeEventListener("pointermove", on)
      window.removeEventListener("pointerdown", on)
    }
  }, [ref])
}

/**
 * Binny peeking up from the bottom edge: his pupils follow the pointer, a speech bubble says one
 * line, and a tap makes him pop up, wiggle his ears and change expression (cycling `moods`; the
 * first is where he starts). Shared by the coming-soon and waitlist-confirmation screens. Key it
 * by state so a new state re-enters. With reduced motion the tap is an instant expression swap.
 */
export function PeekBinny({ moods, bubble, label }: { moods: BinnyMood[]; bubble?: string; label: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useTrack(ref)
  const [i, setI] = useState(0)
  const [pop, setPop] = useState<number | null>(null)
  return (
    <div className="cs-peek" ref={ref}>
      {pop === null && bubble ? (
        <span className="cs-bubble" aria-hidden="true">
          {bubble}
        </span>
      ) : null}
      <button
        type="button"
        className="cs-peek-btn"
        data-pop={pop === null ? undefined : pop % 2}
        aria-label={label}
        onClick={() => {
          setI((n) => (n + 1) % moods.length)
          setPop((n) => (n === null ? 0 : n + 1))
        }}
      >
        <span className="cs-crop">
          <Binny mood={moods[i]} className="cs-binny" />
        </span>
      </button>
    </div>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E3 S4 R5 V3 */
import { useEffect, useState } from "react"
import { Binny } from "@/components/redesign"
import type { DeckOrigin } from "@/lib/flashcardTypes"
import { writingProgress, writingView } from "./deckView"

export function WritingState({ deck, variant }: {
  deck: { topic: string | null; origin: DeckOrigin; requestedCount: number | null }
  variant: "page" | "panel"
}) {
  const view = writingView(deck)
  const [startedAt] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => setElapsed(Date.now() - startedAt), 500)
    return () => window.clearInterval(timer)
  }, [startedAt])
  return (
    <div role="status" className="grid flex-1 content-center justify-items-center gap-3 px-2 pt-7 text-center">
      {variant === "page" ? <Binny mood="thinking" size={96} motion="idle" /> : null}
      <h2 className="mt-1.5 font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-primary">{view.title}</h2>
      <p className="max-w-[30ch] text-[15px] leading-[1.4] text-on-surface-variant">{view.body}</p>
      <div className="h-2 w-[220px] max-w-full overflow-hidden rounded bg-surface-container-high" aria-hidden>
        <i className="block h-full origin-left rounded bg-primary transition-transform duration-[600ms] ease-out motion-reduce:transition-none"
          style={{ transform: `scaleX(${writingProgress(elapsed, deck.requestedCount ?? 12)})` }} />
      </div>
      <p className="text-[14px] leading-[1.4] text-on-surface-variant">{view.hint}</p>
    </div>
  )
}

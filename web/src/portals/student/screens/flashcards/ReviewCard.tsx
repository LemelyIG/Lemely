/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V4 */
import { useEffect, useRef, useState } from "react"
import { useDragGesture } from "@/lib/gestures/useDragGesture"
import { GESTURE_INTERACTIVE_SELECTOR } from "@/lib/gestures/interactiveSelector"
import { GRADE_SWIPE_THRESHOLD, REVEAL_SWIPE_THRESHOLD, flashcardSwipeAction, swipeVisual } from "@/lib/flashcardSwipe"
import type { CardDTO, ReviewGrade } from "@/lib/flashcardTypes"
import { cardSourceLabel } from "./deckView"
import { answerSize, cardScrollStep } from "./reviewView"
import { AiMark } from "./parts/AiMark"
import "./flashcards.css"

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches

/** The stack: an under-card plus the live card (fc.css `.fstage`, `.fcard`, `.under`, `.stamp`). */
export function ReviewCard({
  card, revealed, onReveal, onGrade,
}: { card: CardDTO; revealed: boolean; onReveal: () => void; onGrade: (g: ReviewGrade) => void }) {
  const surface = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const [dx, setDx] = useState(0)
  const [leaving, setLeaving] = useState<"left" | "right" | null>(null)
  const reduced = reducedMotion()
  const visual = swipeVisual(dx, revealed, reduced)

  // Once flipped, focus rests on the card: its name now reads the question then the answer, and Space or Enter does nothing here.
  useEffect(() => { if (revealed) surface.current?.focus() }, [revealed])

  useDragGesture(surface, {
    axis: "x",
    enabled: !leaving,
    commitThreshold: revealed ? GRADE_SWIPE_THRESHOLD : REVEAL_SWIPE_THRESHOLD,
    touchAction: "pan-y",
    startFilter: (e) => {
      const interactive = e.target instanceof Element ? e.target.closest(GESTURE_INTERACTIVE_SELECTOR) : null
      return interactive === null || interactive === surface.current
    },
    onProgress: (x) => setDx(x),
    onCancel: () => setDx(0),
    onCommit: (x) => {
      const action = flashcardSwipeAction({ dx: x, revealed })
      setDx(0)
      if (action === "reveal") onReveal()
      else if (action === "again" || action === "good") {
        if (reduced) { onGrade(action); return }
        setLeaving(action === "good" ? "right" : "left")
        window.setTimeout(() => { setLeaving(null); onGrade(action) }, 240)
      }
    },
  })

  const stampGood = visual.stamp === "good"
  const answerHintId = `fc-answer-hint-${card.id}`
  return (
    <div className="relative mx-2 mb-2.5 mt-3.5 lg:mx-[22px] min-h-[320px] flex-1 [perspective:1200px]">
      <span aria-hidden className="absolute inset-0 translate-y-3 scale-[0.94] rounded-[28px] bg-surface-container-lowest opacity-60 shadow-[inset_0_0_0_1px_var(--color-outline-variant)]" />
      <div
        key={card.id}
        ref={surface}
        role="button"
        data-review-primary=""
        tabIndex={0}
        // No aria-label: the name comes from the visible text (WCAG 2.5.3 label in name), so what a screen reader
        // announces and what a voice-control user reads on the card are the same words in the same order.
        // The flipped state adds its cue as a description, which sits after the name instead of inside it.
        aria-describedby={revealed ? answerHintId : undefined}
        onClick={() => { if (!revealed) onReveal() }}
        // Space or Enter on the focused card flips it. Handled here and stopped, so the screen's window-level
        // shortcut does not flip it a second time; once flipped the card ignores both and they scroll or do nothing.
        onKeyDown={(e) => {
          // A card taller than its face scrolls inside it; the focused card forwards the scroll keys to that body.
          const scroller = body.current
          const step = scroller && scroller.scrollHeight > scroller.clientHeight ? cardScrollStep(e.key, scroller.clientHeight) : 0
          if (scroller && step !== 0) {
            e.preventDefault()
            e.stopPropagation()
            scroller.scrollBy({ top: step, behavior: reduced ? "auto" : "smooth" })
            return
          }
          if (revealed || e.repeat || (e.key !== " " && e.key !== "Enter")) return
          e.preventDefault()
          e.stopPropagation()
          onReveal()
        }}
        style={{ transform: leaving ? undefined : `translateX(${dx}px) rotate(${visual.rotateDeg}deg)` }}
        className={[
          "absolute inset-0 focus-visible:!rounded-[28px] flex flex-col rounded-[28px] bg-surface-container-lowest text-center",
          "shadow-[0_18px_36px_-18px_oklch(0.3_0.06_242/0.4),inset_0_0_0_1px_var(--color-outline-variant)]",
          visual.armed ? (stampGood ? "!shadow-[0_18px_36px_-18px_oklch(0.3_0.06_242/0.4),inset_0_0_0_3px_var(--color-success-text)]" : "!shadow-[0_18px_36px_-18px_oklch(0.3_0.06_242/0.4),inset_0_0_0_3px_var(--color-on-error-container)]") : "",
          revealed ? "animate-[fc-flip_450ms_var(--ease-out)_both] motion-reduce:animate-none" : "animate-[fc-rise_280ms_var(--ease-out)] motion-reduce:animate-none",
          leaving === "right" ? "animate-[fc-out-right_240ms_var(--ease-in-soft)_forwards]" : "",
          leaving === "left" ? "animate-[fc-out-left_240ms_var(--ease-in-soft)_forwards]" : "",
        ].join(" ")}
      >
        {visual.stamp ? (
          <span aria-hidden style={{ opacity: visual.opacity }}
            className={stampGood
              ? "absolute left-[22px] top-[22px] -rotate-[10deg] rounded-[10px] px-3 py-1 text-[18px] font-extrabold text-success-text shadow-[inset_0_0_0_2.5px_var(--color-success-text)]"
              : "absolute right-[22px] top-[22px] rotate-[10deg] rounded-[10px] px-3 py-1 text-[18px] font-extrabold text-on-error-container shadow-[inset_0_0_0_2.5px_var(--color-on-error-container)]"}>
            {stampGood ? "Good" : "Again"}
          </span>
        ) : null}
        {card.source === "ai" ? <span className="absolute bottom-4 right-5"><AiMark label={cardSourceLabel("ai")} /></span> : null}
        {/* The face never grows: a long question scrolls inside this body instead of spilling into the action row below.
            `my-auto` centres short content and, unlike justify-center, never pushes the start of tall content out of reach. */}
        <div
          ref={body}
          data-fc-scroll=""
          className={[
            "flex min-h-0 w-full flex-1 touch-pan-y flex-col items-center overflow-y-auto overflow-x-hidden overscroll-y-contain rounded-[28px] px-7 [scrollbar-width:thin]",
            card.source === "ai" ? "py-10" : "py-7",
          ].join(" ")}
        >
          <div className="my-auto flex max-w-full flex-col items-center gap-[22px]">
            {revealed ? (
              <>
                <span className="max-w-full text-balance break-words text-[20px] font-bold leading-[1.35] text-on-surface-variant">{card.front}</span>
                {" "}
                <span className={`max-w-full break-words font-mono ${answerSize(card.back)} font-bold leading-[1.2] text-on-surface`}>{card.back}</span>
              </>
            ) : (
              <>
                <span className="max-w-full text-balance break-words font-display text-[28px] font-extrabold leading-[1.2] tracking-[-0.02em] text-primary">{card.front}</span>
                {" "}
                <span className="text-[13px] font-semibold text-on-surface-variant">Tap to flip</span>
              </>
            )}
          </div>
        </div>
      </div>
      {revealed ? <span id={answerHintId} className="sr-only">Answer shown. Rate how well you knew it.</span> : null}
    </div>
  )
}

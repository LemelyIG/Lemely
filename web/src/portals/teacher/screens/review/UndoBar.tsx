/* Hallmark · pre-emit critique: P4 H4 E3 S4 R5 V3 */
import { useLayoutEffect, useState, type CSSProperties } from "react"
import { createPortal } from "react-dom"
import type { DecisionNotice } from "./pendingDecisions"
import "./review.css"

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-inverse-primary"

/** The queue column's box, so the desktop toast can sit inside it. Re-measured on resize and scroll-free (fixed). */
function useColumnBox(active: boolean): CSSProperties | undefined {
  const [box, setBox] = useState<CSSProperties | undefined>(undefined)
  useLayoutEffect(() => {
    if (!active) return
    const measure = () => {
      const el = document.querySelector("[data-review-column]")
      if (!el) return setBox(undefined)
      const r = el.getBoundingClientRect()
      const rtl = getComputedStyle(el).direction === "rtl"
      setBox({ insetInlineStart: (rtl ? document.documentElement.clientWidth - r.right : r.left) + 16, maxWidth: Math.max(0, r.width - 32) })
    }
    measure()
    window.addEventListener("resize", measure)
    return () => window.removeEventListener("resize", measure)
  }, [active])
  return box
}

/**
 * The undo toast. Always mounted so the slide in and out can transition; `inert` while hidden.
 *
 * `viewport` (phone, or when there is no column): centred above the bottom nav. `column` (desktop): bottom-start,
 * inside the queue column, so the answer panel's Accept bar is never under it. Both are portalled to the body,
 * because the screen wrapper animates a transform, which would make `fixed` relative to it instead of the viewport.
 */
export function UndoBar({ notice, onUndo, onClose, placement }: { notice: DecisionNotice | null; onUndo: () => void; onClose: () => void; placement: "viewport" | "column" }) {
  const on = notice !== null
  const box = useColumnBox(placement === "column")
  const place = placement === "viewport" || !box
    ? "inset-x-4 mx-auto w-fit max-w-[calc(100vw-32px)] max-sidebar:bottom-[calc(var(--bottom-nav-height)+16px)] shell-lg:start-[calc(var(--shell-sidebar-width)+16px)]"
    : ""
  return createPortal(
    <div
      role={notice?.kind === "error" ? "alert" : "status"}
      aria-live="polite"
      inert={!on}
      style={placement === "column" ? box : undefined}
      className={`lm-rq-toast fixed bottom-6 z-40 flex items-center gap-4 rounded-2xl bg-inverse-surface px-4 py-3 text-[14px] text-inverse-on-surface shadow-[0_30px_60px_-40px_oklch(0.3_0.06_242/0.45)] ${place} ${on ? "pointer-events-auto translate-y-0 opacity-100" : "pointer-events-none translate-y-5 opacity-0"}`}
    >
      <span className="min-w-0">{notice?.text}</span>
      {notice?.undo ? (
        <button type="button" onClick={onUndo} className={`rounded-lg px-2 text-[14px] font-bold text-inverse-primary pointer-coarse:min-h-11 ${FOCUS}`}>Undo</button>
      ) : null}
      {notice && !notice.undo ? (
        <button type="button" onClick={onClose} aria-label="Close" className={`grid size-8 place-items-center rounded-lg text-inverse-primary pointer-coarse:size-11 ${FOCUS}`}>×</button>
      ) : null}
    </div>,
    document.body,
  )
}

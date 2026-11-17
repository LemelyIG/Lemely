import type { DecisionNotice } from "./pendingDecisions"
import "./review.css"

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-inverse-primary"

/** The undo toast. Always mounted so the slide in and out can transition; `inert` while hidden. */
export function UndoBar({ notice, onUndo, onClose }: { notice: DecisionNotice | null; onUndo: () => void; onClose: () => void }) {
  const on = notice !== null
  return (
    <div
      role={notice?.kind === "error" ? "alert" : "status"}
      aria-live="polite"
      inert={!on}
      className={`lm-rq-toast fixed bottom-6 start-1/2 z-40 flex max-w-[calc(100vw-32px)] items-center gap-4 rounded-2xl bg-inverse-surface px-4 py-3 text-[14px] text-inverse-on-surface shadow-[0_30px_60px_-40px_oklch(0.3_0.06_242/0.45)] max-sidebar:bottom-[calc(var(--bottom-nav-height)+16px)] ${on ? "pointer-events-auto -translate-x-1/2 translate-y-0 opacity-100" : "pointer-events-none -translate-x-1/2 translate-y-5 opacity-0"}`}
    >
      <span>{notice?.text}</span>
      {notice?.undo ? (
        <button type="button" onClick={onUndo} className={`rounded-lg px-2 text-[14px] font-bold text-inverse-primary pointer-coarse:min-h-11 ${FOCUS}`}>Undo</button>
      ) : null}
      {notice && !notice.undo ? (
        <button type="button" onClick={onClose} aria-label="Close" className={`grid size-8 place-items-center rounded-lg text-inverse-primary pointer-coarse:size-11 ${FOCUS}`}>×</button>
      ) : null}
    </div>
  )
}

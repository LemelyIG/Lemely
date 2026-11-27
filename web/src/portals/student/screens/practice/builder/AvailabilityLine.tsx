/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
/* L4 · the live "what matches" line (the mock's `avl`, `avl.wait`, `avl.no`, plus the check-failed case with its retry). */
import { cn } from "@/lib/utils"
import { MonoNumbers } from "../hub/MonoNumbers"
import { SpinnerRing, TickIcon } from "../practiceIcons"
import type { AvailabilityLine as Line } from "./builderModel"

const TONE: Record<Line["tone"], string> = {
  ok: "text-success-text",
  wait: "text-on-surface-variant",
  short: "text-on-tertiary-container",
  none: "text-on-tertiary-container",
  error: "text-error",
}

/** The line is the one live region; its retry sits beside it so the button is not read out as part of the status. */
export function AvailabilityLine({ line, onRetry }: { line: Line; onRetry?: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3">
      <p role="status" className={cn("m-0 flex items-center gap-1.5 text-[13.5px] font-semibold", TONE[line.tone])}>
        {line.tone === "ok" ? <TickIcon /> : null}
        {line.tone === "wait" ? <SpinnerRing /> : null}
        <MonoNumbers text={line.text} />
      </p>
      {line.retry && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex min-h-11 items-center text-[13.5px] font-semibold text-primary underline underline-offset-2 focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          Check again
        </button>
      ) : null}
    </div>
  )
}

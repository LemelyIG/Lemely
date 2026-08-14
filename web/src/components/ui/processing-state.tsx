/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { HTMLAttributes, ReactNode } from "react"
import {
  CheckCircle,
  CircleNotch,
  Circle,
  XCircle,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * C-10 · Processing state — the marking pipeline's staged progress (S-14).
 *
 * HARD PRODUCT REQUIREMENT ("no fake progress bar" — LEMELY_UI_SPEC S-14
 * design note): this renders discrete, independently-stated stages, each
 * with its own success/in-progress/fail state and — for the marking stage —
 * a real per-question counter. There is no single animated bar standing in
 * for the whole pipeline. The only animation is a spinner on the ONE stage
 * that is genuinely, currently running, and that respects
 * prefers-reduced-motion via the global rule in index.css (animate-spin's
 * duration is zeroed there, not re-implemented here).
 *
 * Failure messages are caller-supplied per stage (`errorMessage`) — this
 * component never renders a generic "something went wrong" fallback; per
 * the spec, each stage must fail with a specific, actionable message (mark
 * scheme not found / pages unreadable / service unavailable, etc.).
 */

export type ProcessingStageStatus = "pending" | "active" | "done" | "error"

export interface ProcessingStageProgress {
  current: number
  total: number
  /** e.g. "question" → renders "Question 7 of 21". Defaults to "item". */
  unit?: string
}

export interface ProcessingStage {
  id: string
  label: string
  status: ProcessingStageStatus
  /** Real, specific detail shown while active/done (e.g. "Reading page 4 of 6"). */
  detail?: string
  /** Required by product rule when status === "error" — no generic fallback is rendered if omitted. */
  errorMessage?: string
  /** Marking stage: per-question counter. */
  progress?: ProcessingStageProgress
}

export interface ProcessingStateProps extends HTMLAttributes<HTMLDivElement> {
  stages: ProcessingStage[]
  /** Optional trailing slot — e.g. "You can leave, we'll notify you" + a button (S-14). */
  footer?: ReactNode
  className?: string
}

function capitalize(word: string) {
  return word.length === 0 ? word : word[0].toUpperCase() + word.slice(1)
}

/* The stage vocabulary, exported because the teacher grading console renders a
 * second pipeline panel from a different wire type (`PipelineStep`, a stored
 * per-paper summary rather than a live SSE stream) and drew its own glyphs
 * until P7.1. `pipelineStages.ts` already states the rule this serves: a
 * progress panel that reports the pipeline differently depending on where you
 * are is the "roughly true" UI S-14 forbids — and the same screen showing it
 * two ways is that rule's worst case.
 *
 * Every state carries an accessible name, not only `active`. Until P7.1 the
 * other three had none, so a reader who could not see the icon got the stage
 * label and nothing about whether it had run: done, not started and failed
 * were announced identically, distinguished on screen by shape and colour
 * alone. `role="img"` because an `aria-label` on a bare `<svg>` is not
 * reliably announced without it. */
export function StageGlyph({ status }: { status: ProcessingStageStatus }) {
  if (status === "done") {
    return (
      <CheckCircle size={20} weight="fill" className="text-ok" role="img" aria-label="Done" />
    )
  }
  if (status === "active") {
    return (
      <CircleNotch
        size={20}
        className="animate-spin text-accent"
        role="img"
        aria-label="In progress"
      />
    )
  }
  if (status === "error") {
    return <XCircle size={20} weight="fill" className="text-err" role="img" aria-label="Failed" />
  }
  return <Circle size={20} className="text-rule" role="img" aria-label="Not started" />
}

export function ProcessingState({
  stages,
  footer,
  className,
  ...props
}: ProcessingStateProps) {
  return (
    <div className={cn("flex flex-col", className)} {...props}>
      {stages.map((stage, i) => {
        const isLast = i === stages.length - 1
        return (
          <div key={stage.id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <StageGlyph status={stage.status} />
              {!isLast ? (
                <span
                  className={cn(
                    "min-h-4 w-px flex-1",
                    stage.status === "done" ? "bg-ok" : "bg-rule",
                  )}
                />
              ) : null}
            </div>
            <div className={cn("min-w-0 flex-1", !isLast && "pb-5")}>
              <div className="flex items-center justify-between gap-2">
                <span
                  className={cn(
                    "text-body-md font-medium",
                    stage.status === "pending" ? "text-ink-faint" : "text-ink",
                  )}
                >
                  {stage.label}
                </span>
                {stage.status === "active" && stage.progress ? (
                  <span className="flex-none text-data-sm text-ink-muted">
                    {capitalize(stage.progress.unit ?? "item")} {stage.progress.current} of{" "}
                    {stage.progress.total}
                  </span>
                ) : null}
              </div>
              {stage.status === "error" && stage.errorMessage ? (
                <p className="mt-1 text-body-md text-err">{stage.errorMessage}</p>
              ) : stage.detail ? (
                <p className="mt-1 text-body-sm text-ink-faint">{stage.detail}</p>
              ) : null}
            </div>
          </div>
        )
      })}
      {footer ? <div className="mt-2 border-t border-rule pt-4">{footer}</div> : null}
    </div>
  )
}

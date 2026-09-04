/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { HTMLAttributes, ReactNode } from "react"
import { Check, CircleNotch, DotsThree, X } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * C-10 · Processing state — the marking pipeline's staged progress (S-14).
 *
 * HARD PRODUCT REQUIREMENT ("no fake progress bar" — LEMELY_UI_SPEC S-14
 * design note): this renders discrete, independently-stated stages, each
 * with its own success/in-progress/fail state and — for the marking stage —
 * a real per-question counter. There is no single animated bar standing in
 * for the whole pipeline: the spinner, its pulsing ring, and the
 * width-transitioning counter bar are all scoped to the ONE stage that is
 * genuinely, currently running, and only render a numeric bar at all when
 * that stage carries a real `progress` value. Every animation here —
 * `animate-spin`, `animate-ping`, and the plain CSS `transition`s on colour
 * and width — respects prefers-reduced-motion via the global `*` rule in
 * index.css; none of it is re-implemented per-component.
 *
 * Failure messages are caller-supplied per stage (`errorMessage`) — this
 * component never renders a generic "something went wrong" fallback; per
 * the spec, each stage must fail with a specific, actionable message (mark
 * scheme not found / pages unreadable / service unavailable, etc.).
 */

export type ProcessingStageStatus = "pending" | "active" | "done" | "error"

export interface ProcessingStageProgress {
  current: number
  /**
   * Undefined exactly when the wire couldn't tell us a total (a request that
   * isn't length-computable, e.g. an upload over a connection that never
   * reports `Content-Length` framing) — not a value to fill in on its behalf.
   * `StageProgressBar` reads this as the indeterminate case: a running label
   * with no bar and no percentage, since a bar implies a known endpoint this
   * reading does not have.
   */
  total?: number
  /** e.g. "question" → renders "Question 7 of 21". Defaults to "item".
   * Ignored when `label` is set. */
  unit?: string
  /**
   * A preformatted replacement for the "{Unit} {current} of {total}" text —
   * e.g. `"3.2 MB of 8.1 MB"` for the upload stage, where the wire unit is
   * bytes and the default phrasing would read "Byte 3355443 of 8493465". The
   * bar itself still runs off `current`/`total` unchanged; only the text row
   * above it is replaced.
   */
  label?: string
}

export interface ProcessingStage {
  id: string
  label: string
  status: ProcessingStageStatus
  /** Real, specific detail shown while active/done (e.g. "Reading page 4 of 6"). */
  detail?: string
  /** Required by product rule when status === "error" — no generic fallback is rendered if omitted. */
  errorMessage?: string
  /** A real counter for the stage currently running — the marking stage's
   * per-question count, or the upload stage's bytes moved. */
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
  /* One ring geometry for all four states, so the badges line up on the
   * connector and only their colour/contents change between stages. */
  const ring =
    "flex h-7 w-7 flex-none items-center justify-center rounded-full border-2 bg-paper-raised"

  if (status === "done") {
    return (
      <span
        className={cn(
          ring,
          "border-ok text-ok",
          "transition-transform duration-[var(--dur-fast)] ease-out-soft hover:scale-110",
        )}
      >
        <Check size={15} weight="bold" role="img" aria-label="Done" />
      </span>
    )
  }
  if (status === "active") {
    return (
      /* The label lives on the wrapper, not on `CircleNotch`: the notched ring
       * and the centre dot are one indicator, and announcing the arc alone
       * would name a decoration rather than the state. */
      <span
        className="relative flex h-7 w-7 flex-none items-center justify-center text-accent"
        role="img"
        aria-label="In progress"
      >
        {/* Pulsing outer ring — the ONE stage that is genuinely running gets
         * this extra emphasis; every other status is deliberately still.
         * `animate-ping` is Tailwind's built-in keyframe, so it is already
         * caught by the global `prefers-reduced-motion` rule in index.css
         * (a bare `*` selector) without any component-level handling. */}
        <span
          aria-hidden="true"
          className="absolute inset-0 rounded-full bg-accent-wash animate-ping"
        />
        <CircleNotch
          size={28}
          weight="bold"
          aria-hidden="true"
          className="absolute inset-0 animate-spin"
        />
        <span aria-hidden="true" className="relative h-1.5 w-1.5 rounded-full bg-accent" />
      </span>
    )
  }
  if (status === "error") {
    return (
      <span className={cn(ring, "border-err text-err")}>
        <X size={15} weight="bold" role="img" aria-label="Failed" />
      </span>
    )
  }
  return (
    <span className={cn(ring, "border-rule text-ink-faint")}>
      <DotsThree size={16} weight="bold" role="img" aria-label="Not started" />
    </span>
  )
}

/* The kicker above each stage label ("Phase 2", "Active phase", "Final
 * phase"), uppercased by the `text-eyebrow` rung. Derived from position and
 * status — both facts this component already has — rather than from anything
 * the caller has to supply and could get out of step with the stage list.
 *
 * Returns null for a one-stage list: "Final phase" over a lone "Uploading the
 * scan" (the teacher console's upload control) would imply a sequence that
 * does not exist. A kicker numbering a sequence needs a sequence. */
function phaseKicker(
  index: number,
  count: number,
  status: ProcessingStageStatus,
): string | null {
  if (count < 2) return null
  if (status === "active") return "Active phase"
  if (index === count - 1) return "Final phase"
  return `Phase ${index + 1}`
}

/* Real progress only, per S-14 — never estimated. Two wire sources feed
 * `stage.progress`: `frameProgress` in `pipelineStages.ts`, which only ever
 * populates it from an actual `index`/`total` the backend sent, and the
 * upload stage's own `xhr.upload.onprogress` bytes (`CorrectPaper.tsx`'s
 * `uploadStageProgress`). Both are genuine wire signal, not a derived guess,
 * which is what this component actually enforces — it is agnostic about
 * *which* real counter it is handed. It never estimates a percentage from
 * stage position, elapsed time, or anything else that isn't a number the
 * wire actually reported.
 *
 * Two things render nothing rather than a fabricated fact: this whole
 * component is skipped by its caller when `stage.progress` itself is
 * undefined (no counter has arrived yet), and below, a `progress.total` of
 * `undefined` renders the label alone with no bar and no percentage — the
 * indeterminate case, where the wire has bytes moved but no total to measure
 * them against. A bar or a percentage would claim a known endpoint that
 * reading does not have. */
function StageProgressBar({ progress }: { progress: ProcessingStageProgress }) {
  const unit = capitalize(progress.unit ?? "item")

  if (progress.total === undefined) {
    return (
      <div className="mt-3 rounded-md border border-rule bg-paper-sunk p-3">
        <span className="text-data-sm text-ink-muted">
          {progress.label ?? `${unit} ${progress.current}`}
        </span>
      </div>
    )
  }

  const pct = Math.max(0, Math.min(100, Math.round((progress.current / progress.total) * 100)))
  return (
    <div className="mt-3 rounded-md border border-rule bg-paper-sunk p-3">
      <div className="mb-2 flex items-center justify-between gap-2 text-data-sm">
        <span className="text-ink-muted">
          {progress.label ?? `${unit} ${progress.current} of ${progress.total}`}
        </span>
        <span className="flex-none text-accent-ink">{pct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-rule">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-[var(--dur-slow)] ease-out-soft"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
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
        const kicker = phaseKicker(i, stages.length, stage.status)
        return (
          <div key={stage.id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <StageGlyph status={stage.status} />
              {!isLast ? (
                <span
                  className={cn(
                    "min-h-4 w-px flex-1 transition-colors duration-[var(--dur-slow)] ease-out-soft",
                    stage.status === "done" ? "bg-ok" : "bg-rule",
                  )}
                />
              ) : null}
            </div>
            <div className={cn("min-w-0 flex-1 pt-0.5", !isLast && "pb-5")}>
              {kicker ? (
                <span
                  className={cn(
                    "block text-eyebrow transition-colors duration-[var(--dur-fast)]",
                    stage.status === "pending" && "text-ink-faint",
                    stage.status === "active" && "text-accent-ink",
                    stage.status === "done" && "text-ink-muted",
                    stage.status === "error" && "text-err",
                  )}
                >
                  {kicker}
                </span>
              ) : null}
              <span
                className={cn(
                  "block text-body-md transition-colors duration-[var(--dur-fast)]",
                  kicker && "mt-1.5",
                  stage.status === "pending" && "font-medium text-ink-faint",
                  stage.status === "active" && "font-semibold text-ink",
                  (stage.status === "done" || stage.status === "error") &&
                    "font-medium text-ink",
                )}
              >
                {stage.label}
              </span>
              {stage.status === "error" && stage.errorMessage ? (
                <p className="mt-1 text-body-md text-err">{stage.errorMessage}</p>
              ) : stage.detail ? (
                <p className="mt-1 text-body-sm text-ink-faint">{stage.detail}</p>
              ) : null}
              {/* The animated bar is scoped to the one stage carrying a real
               * counter (S-14's "no fake progress bar" — see header comment).
               * It never stands in for the whole pipeline's completion. */}
              {stage.status === "active" && stage.progress ? (
                <StageProgressBar progress={stage.progress} />
              ) : null}
            </div>
          </div>
        )
      })}
      {footer ? <div className="mt-2 border-t border-rule pt-4">{footer}</div> : null}
    </div>
  )
}

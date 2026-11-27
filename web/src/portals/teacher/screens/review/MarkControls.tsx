/* Hallmark · pre-emit critique: P5 H4 E4 S5 R4 V4 */
import type { MarkPoint, MarkState } from "./markModel"
import { canStep, deltaLine, isBlocked, orBefore, poolHeader, stepDown, stepUp, toggleTick, totalOf } from "./markModel"
import { Tick } from "./Tick"

const STEP_BTN =
  "grid size-10 place-items-center rounded-chip bg-surface-container-lowest text-2xl font-bold leading-none text-primary transition-transform duration-150 active:scale-95 disabled:opacity-35 pointer-coarse:size-12 motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"

export interface MarkControlsProps {
  points: MarkPoint[]
  state: MarkState
  max: number | null
  lemely: number | null
  disabled: boolean
  disabledReason: string | null
  clampNote: string | null
  matchedPointIds: string[]
  onChange: (s: MarkState) => void
}

/** The tick stepper and the scheme points. The ticks are the source of truth; the stepper moves them. */
export function MarkControls({ points, state, max, lemely, disabled, disabledReason, clampNote, matchedPointIds, onChange }: MarkControlsProps) {
  const total = totalOf(points, state, max)
  const step = canStep(points, state, max)
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3.5 shell-sm:justify-start">
        <div className="inline-flex items-center gap-0.5 rounded-2xl bg-primary-container p-1">
          <button type="button" aria-label="One mark less" disabled={disabled || !step.down} onClick={() => onChange(stepDown(points, state, max))} className={STEP_BTN}>−</button>
          <span key={total} className="rq-bump min-w-[76px] text-center font-mono text-xl font-semibold tabular-nums" aria-live="polite">{total}/{max ?? "–"}</span>
          <button type="button" aria-label="One mark more" disabled={disabled || !step.up} onClick={() => onChange(stepUp(points, state, max))} className={STEP_BTN}>+</button>
        </div>
        <span className="font-mono text-dense-sm font-semibold tracking-[-0.01em] text-on-surface-variant">{deltaLine(total, lemely)}</span>
      </div>
      {clampNote ? <p className="text-dense text-on-surface-variant">{clampNote}</p> : null}
      {disabled && disabledReason ? <p className="text-dense text-on-surface-variant">{disabledReason}</p> : null}
      {points.length > 0 ? (
        <div role="group" aria-label="Marking points" className="grid gap-1.5">
          {points.map((p, i) => {
            const on = state.ticked.includes(p.markPointId)
            const blocked = disabled || isBlocked(points, state, p.markPointId, max)
            const pool = poolHeader(points, i)
            return (
              <div key={p.markPointId} className="contents">
                {pool ? <div className="pt-1 text-center font-mono text-xs font-semibold uppercase tracking-[0.08em] text-on-surface-variant">{pool}</div> : null}
                {orBefore(points, i) ? <div className="-my-0.5 text-center font-mono text-xs font-semibold tracking-[0.08em] text-on-surface-variant" aria-hidden="true">OR</div> : null}
                <button
                  type="button"
                  data-testid="marker-verdict-row"
                  aria-pressed={on}
                  disabled={!on && blocked}
                  onClick={() => onChange(toggleTick(points, state, p.markPointId, max))}
                  className={`flex w-full items-start gap-2.5 rounded-chip px-3 py-2.5 text-start text-sm leading-[1.4] transition-colors duration-150 motion-reduce:transition-none disabled:cursor-not-allowed disabled:opacity-40 pointer-coarse:min-h-12 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${on ? "bg-success-container" : "bg-surface-container-low hover:bg-surface-container"}`}
                >
                  <span className={`mt-px grid size-5 flex-none place-items-center rounded-bar text-on-primary ${on ? "bg-success" : "bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline)]"}`} aria-hidden="true">{on ? <Tick size={12} /> : null}</span>
                  <span className="grid min-w-0 gap-0.5">
                    <span><b className="font-mono text-dense-sm font-semibold">{p.code}</b> {p.text}</span>
                    {p.verdictLabel || p.ecf ? (
                      <span className="flex flex-wrap gap-2 text-dense-sm text-on-surface-variant">
                        {p.verdictLabel ? <span>{p.verdictLabel}</span> : null}
                        {p.ecf ? <span>Carried forward</span> : null}
                      </span>
                    ) : null}
                    {p.note ? <span data-testid="point-note" className="line-clamp-2 text-dense-sm text-on-surface-variant" title={p.note}>{p.note}</span> : null}
                  </span>
                  <span className="ms-auto flex-none rounded-row bg-surface-container-lowest px-[7px] py-px font-mono text-xs font-semibold">{p.tariff} {p.tariff === 1 ? "mark" : "marks"}</span>
                </button>
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-dense text-on-surface-variant">
          {matchedPointIds.length > 0 ? `Matched scheme points: ${matchedPointIds.join(", ")}` : "No points matched."}
        </p>
      )}
    </>
  )
}

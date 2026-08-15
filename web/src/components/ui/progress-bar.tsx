import { useId } from "react"
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * Determinate + indeterminate progress meter. `--paper-sunk` track, 6px tall,
 * fill in `--accent` by default (an `err`/`ok` tone is available for a
 * validation-flavoured progress, e.g. a marking run that has already hit
 * failures).
 *
 * DESIGN.md §9.2 bans animating anything but `transform`/`opacity`. That
 * ruled out the obvious "fill's `width` grows from 0% to value%" approach for
 * BOTH variants:
 *   - Determinate: the fill is a full-width layer scaled with
 *     `transform: scaleX()` from a fixed `transform-origin`, not resized.
 *   - Indeterminate: a short segment translates back and forth via
 *     `transform: translateX()` rather than a sweeping `background-position`
 *     or `width` pulse.
 * `prefers-reduced-motion` needs no special-casing here: index.css's global
 * rule already forces every `animation-duration` to ~0 under that media
 * query, which freezes the indeterminate sweep without this component having
 * to know about it.
 */

export type ProgressTone = "accent" | "ok" | "err"

const toneClasses: Record<ProgressTone, string> = {
  accent: "bg-accent",
  ok: "bg-ok",
  err: "bg-err",
}

export interface ProgressBarProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  /**
   * 0–100. Omit (or pass `indeterminate`) when the total is unknown — e.g. a
   * marking job whose page count hasn't been read yet.
   */
  value?: number
  /** Renders the animated indeterminate sweep instead of a fixed fill.
   * Ignored (treated as false) if `value` is also given, since a caller that
   * supplies both almost certainly means "no longer indeterminate now that I
   * have a value" rather than "animate anyway". */
  indeterminate?: boolean
  tone?: ProgressTone
  /**
   * Visible label rendered above the bar (e.g. "Marking paper 3 of 12").
   * Optional — when omitted, `ariaLabel` must describe the bar for
   * assistive tech, since a bare unlabelled progressbar is meaningless to a
   * screen-reader user.
   */
  label?: string
  /** Accessible name when there is no visible `label` (e.g. a compact bar
   * embedded in a table cell). Ignored when `label` is present, since the
   * visible label already supplies the accessible name via `aria-labelledby`. */
  ariaLabel?: string
}

export function ProgressBar({
  value,
  indeterminate = false,
  tone = "accent",
  label,
  ariaLabel,
  className,
  ...props
}: ProgressBarProps) {
  const isIndeterminate = indeterminate && value === undefined
  const clamped = value === undefined ? 0 : Math.max(0, Math.min(100, value))
  const labelId = useId()

  return (
    <div className={cn("flex flex-col gap-1.5", className)} {...props}>
      {label ? (
        <div id={labelId} className="flex items-center justify-between text-body-sm text-ink-muted">
          <span>{label}</span>
          {!isIndeterminate ? (
            <span className="text-data-sm text-ink-faint">{Math.round(clamped)}%</span>
          ) : null}
        </div>
      ) : null}
      <div
        role="progressbar"
        aria-valuenow={isIndeterminate ? undefined : Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-labelledby={label ? labelId : undefined}
        aria-label={!label ? ariaLabel : undefined}
        className="relative h-1.5 w-full overflow-hidden rounded-full bg-paper-sunk"
      >
        {isIndeterminate ? (
          <div
            className={cn(
              "absolute inset-y-0 w-1/3 rounded-full motion-safe:animate-[lm-progress-indeterminate_calc(var(--dur-base)*4)_var(--ease-out-soft)_infinite]",
              toneClasses[tone],
            )}
          />
        ) : (
          <div
            className={cn(
              "absolute inset-0 origin-left rtl:origin-right rounded-full transition-transform duration-[var(--dur-base)] ease-out-soft",
              toneClasses[tone],
            )}
            style={{ transform: `scaleX(${clamped / 100})` }}
          />
        )}
      </div>
      {/* Scoped keyframes for the indeterminate sweep. A component-local
          <style> tag rather than a new rule in index.css: this is the only
          consumer of this exact animation, and index.css's `@keyframes`
          block is reserved for product-wide motion (the file's own header
          says as much) rather than a single component's implementation
          detail. -100%/280% travels the segment fully off each edge so it
          never appears to "pop" at the track boundary. */}
      {isIndeterminate ? (
        <style>{`
          @keyframes lm-progress-indeterminate {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(280%); }
          }
        `}</style>
      ) : null}
    </div>
  )
}

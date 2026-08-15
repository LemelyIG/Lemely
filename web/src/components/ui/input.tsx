import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react"
import { CheckCircle, CircleNotch, WarningCircle } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/**
 * A field's async/validation state, layered on top of its native disabled
 * state. `"error"` and `"success"` are mutually exclusive outcomes of
 * validation; `"loading"` is for an in-flight async check (e.g. "checking
 * availability…") and forces the field read-only for the duration — a user
 * should never be able to edit a value while a stale validation result for
 * the previous value is still in flight, since that produces a race where
 * the wrong result lands after the new keystrokes.
 */
export type FieldState = "error" | "success" | "loading"

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  /**
   * Always required, never optional. DESIGN.md §12 bans placeholder-as-label
   * outright, so there is no prop path that lets a caller ship a field with
   * no visible label — `placeholder` remains available on the native input
   * for a genuine format hint ("YYYY-MM-DD"), but it is not accepted as a
   * substitute for this.
   */
  label: string
  /** Supporting copy shown under the field when there is no error. Replaced
   * by the error message when one is present, never shown alongside it —
   * two competing lines under one field is noise, and the error is always
   * the more actionable of the two. */
  hint?: string
  /** Presence alone is enough to put the field into its error state; passing
   * `state="error"` too is redundant but harmless. Rendered inline, right
   * under the field, per DESIGN.md §12 ("errors inline and adjacent to the
   * field, never only at the top of the form"). */
  error?: string
  state?: FieldState
  /** Rendered inside the field's start inset. Decorative only — pass an
   * `aria-hidden` icon; the visible label already carries the field's name. */
  leadingIcon?: ReactNode
  /** Rendered inside the field's end inset. Suppressed automatically while
   * loading/success/error render their own status glyph in that slot, so a
   * caller's icon and the status glyph never collide. */
  trailingIcon?: ReactNode
  /** Class names for the outer `<div>` wrapping label + field + hint. */
  wrapperClassName?: string
  labelClassName?: string
}

/**
 * Text input with a visible label, optional hint/error copy, and optional
 * leading/trailing icon slots.
 *
 * The border-colour ladder (`rule` → `rule-strong` on hover/focus → `err`/`ok`
 * for validation) is DESIGN.md §12's exact spec for this component. Focus
 * itself is left to the global `:focus-visible` outline (index.css) rather
 * than re-implemented here with a ring utility — duplicating it would risk
 * the two drifting apart, and the global rule already covers keyboard-only
 * visibility correctly.
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    label,
    hint,
    error,
    state,
    leadingIcon,
    trailingIcon,
    className,
    wrapperClassName,
    labelClassName,
    id,
    disabled,
    ...props
  },
  ref,
) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const hintId = hint && !error ? `${inputId}-hint` : undefined
  const errorId = error ? `${inputId}-error` : undefined

  // An explicit `error` string always wins over a caller-passed `state` —
  // a field cannot be simultaneously "successfully validated" and carrying
  // an error message, so there is no ambiguity to preserve here.
  const resolvedState: FieldState | undefined = error ? "error" : state
  const isLoading = resolvedState === "loading"
  const showStatusGlyph = resolvedState === "error" || resolvedState === "success" || isLoading

  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      <label htmlFor={inputId} className={cn("text-label text-ink", labelClassName)}>
        {label}
      </label>
      <div className="relative">
        {leadingIcon ? (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-y-0 start-3 flex items-center text-ink-faint"
          >
            {leadingIcon}
          </span>
        ) : null}
        <input
          ref={ref}
          id={inputId}
          disabled={disabled || isLoading}
          aria-invalid={resolvedState === "error" || undefined}
          aria-busy={isLoading || undefined}
          aria-describedby={cn(errorId, hintId) || undefined}
          className={cn(
            "w-full rounded-md border bg-paper-raised px-3 py-2 text-body-md text-ink placeholder:text-ink-faint",
            "transition-colors duration-[var(--dur-instant)] ease-out-soft",
            "border-rule hover:border-rule-strong focus-visible:border-rule-strong active:border-rule-strong",
            "disabled:cursor-not-allowed disabled:bg-paper-sunk disabled:text-ink-faint disabled:hover:border-rule",
            leadingIcon && "ps-9",
            (trailingIcon || showStatusGlyph) && "pe-9",
            resolvedState === "error" && "border-err hover:border-err focus-visible:border-err",
            resolvedState === "success" && "border-ok hover:border-ok focus-visible:border-ok",
            className,
          )}
          {...props}
        />
        {isLoading ? (
          <CircleNotch
            aria-hidden
            className="pointer-events-none absolute inset-y-0 end-3 my-auto h-4 w-4 animate-spin text-ink-faint"
          />
        ) : resolvedState === "success" ? (
          <CheckCircle
            aria-hidden
            weight="regular"
            className="pointer-events-none absolute inset-y-0 end-3 my-auto h-4 w-4 text-ok"
          />
        ) : resolvedState === "error" ? (
          <WarningCircle
            aria-hidden
            weight="regular"
            className="pointer-events-none absolute inset-y-0 end-3 my-auto h-4 w-4 text-err"
          />
        ) : trailingIcon ? (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-y-0 end-3 flex items-center text-ink-faint"
          >
            {trailingIcon}
          </span>
        ) : null}
      </div>
      {error ? (
        <p id={errorId} className="text-body-sm text-err">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-body-sm text-ink-muted">
          {hint}
        </p>
      ) : null}
    </div>
  )
})

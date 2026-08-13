import { forwardRef, useId, type SelectHTMLAttributes } from "react"
import { CaretDown, CircleNotch, WarningCircle } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import type { FieldState } from "@/components/ui/input"

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string
  hint?: string
  error?: string
  state?: FieldState
  wrapperClassName?: string
  labelClassName?: string
}

/**
 * Native `<select>` styled to match `Input`, deliberately not a custom
 * listbox. A hand-rolled popover-based listbox has to re-implement typeahead,
 * keyboard paging, native mobile picker UI, and screen-reader semantics that
 * the platform control gets for free — and on iOS/Android in particular a
 * custom listbox is usually a *worse* picker than the OS wheel/sheet the
 * native element already opens. The only piece we own is the chevron, which
 * is decorative (`aria-hidden`) and layered over the native control rather
 * than replacing it; `appearance-none` removes the browser's own arrow so
 * ours is the only one, but every other behaviour — opening, closing,
 * typeahead, option rendering — stays native.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  {
    label,
    hint,
    error,
    state,
    className,
    wrapperClassName,
    labelClassName,
    id,
    disabled,
    children,
    ...props
  },
  ref,
) {
  const generatedId = useId()
  const selectId = id ?? generatedId
  const hintId = hint && !error ? `${selectId}-hint` : undefined
  const errorId = error ? `${selectId}-error` : undefined

  const resolvedState: FieldState | undefined = error ? "error" : state
  const isLoading = resolvedState === "loading"

  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      <label htmlFor={selectId} className={cn("text-label text-ink", labelClassName)}>
        {label}
      </label>
      <div className="relative">
        <select
          ref={ref}
          id={selectId}
          disabled={disabled || isLoading}
          aria-invalid={resolvedState === "error" || undefined}
          aria-busy={isLoading || undefined}
          aria-describedby={cn(errorId, hintId) || undefined}
          className={cn(
            "w-full appearance-none rounded-md border bg-paper-raised ps-3 pe-9 py-2 text-body-md text-ink",
            "transition-colors duration-[var(--dur-instant)] ease-out-soft",
            "border-rule hover:border-rule-strong focus-visible:border-rule-strong active:border-rule-strong",
            "disabled:cursor-not-allowed disabled:bg-paper-sunk disabled:text-ink-faint disabled:hover:border-rule",
            resolvedState === "error" && "border-err hover:border-err focus-visible:border-err",
            resolvedState === "success" && "border-ok hover:border-ok focus-visible:border-ok",
            className,
          )}
          {...props}
        >
          {children}
        </select>
        {isLoading ? (
          <CircleNotch
            aria-hidden
            className="pointer-events-none absolute inset-y-0 end-3 my-auto h-4 w-4 animate-spin text-ink-faint"
          />
        ) : resolvedState === "error" ? (
          <WarningCircle
            aria-hidden
            weight="regular"
            className="pointer-events-none absolute inset-y-0 end-3 my-auto h-4 w-4 text-err"
          />
        ) : (
          <CaretDown
            aria-hidden
            weight="regular"
            className="pointer-events-none absolute inset-y-0 end-3 my-auto h-4 w-4 text-ink-faint"
          />
        )}
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

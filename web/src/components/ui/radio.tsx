import {
  createContext,
  forwardRef,
  useContext,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
} from "react"
import { CheckCircle, CircleNotch, WarningCircle } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import type { FieldState } from "@/components/ui/input"

interface RadioGroupContextValue {
  name: string
  value?: string
  onValueChange?: (value: string) => void
  disabled?: boolean
}

const RadioGroupContext = createContext<RadioGroupContextValue | null>(null)

export interface RadioGroupProps {
  /** Rendered as the `<fieldset>`'s `<legend>`. A radio group's name is
   * announced by AT before every option in the group, so — unlike a single
   * field, where a caller can sometimes argue context makes a label
   * redundant — this one is not optional. */
  label: string
  /** Shared `name` for the underlying radios. Generated with `useId` if
   * omitted, so two groups on the same page never collide. */
  name?: string
  value?: string
  onValueChange?: (value: string) => void
  hint?: string
  error?: string
  /**
   * Validation/async state, matching `Input`, `Select`, `Textarea`, `Switch`
   * and `Checkbox`. A radio group is a form field like any other and needs the
   * same three outcomes a `<select>` has: an in-flight async check
   * ("checking availability"), a passed check, and a failed one.
   *
   * Added after the kit was assembled: the group originally carried only
   * `error`, which meant a form could show a green tick beside a select and
   * nothing at all beside a radio group validated the same way. That
   * inconsistency is the kind that gets discovered halfway through building a
   * form, so it is closed here rather than worked around at the call site.
   *
   * `error` (the message) still wins over `state`, since a field cannot be
   * simultaneously "successfully validated" and carrying a validation message.
   */
  state?: FieldState
  disabled?: boolean
  orientation?: "vertical" | "horizontal"
  className?: string
  /** One `<Radio>` per option. */
  children: ReactNode
}

/**
 * Groups `Radio` children under one accessible name and one `name` attribute,
 * and threads `value`/`onValueChange` down via context so each `Radio` does
 * not need its own `checked`/`onChange` wiring at the call site — the same
 * shape as a controlled `<select>`, just for a mutually-exclusive set of
 * visible options instead of a dropdown.
 */
export function RadioGroup({
  label,
  name,
  value,
  onValueChange,
  hint,
  error,
  state,
  disabled,
  orientation = "vertical",
  className,
  children,
}: RadioGroupProps) {
  const generatedName = useId()
  const groupName = name ?? generatedName
  const hintId = hint && !error ? `${groupName}-hint` : undefined
  const errorId = error ? `${groupName}-error` : undefined
  const resolvedState: FieldState | undefined = error ? "error" : state
  const isLoading = resolvedState === "loading"

  return (
    <fieldset
      className={cn("m-0 flex flex-col gap-2 border-0 p-0", className)}
      disabled={disabled}
      aria-invalid={!!error || undefined}
      aria-busy={isLoading || undefined}
      aria-describedby={cn(errorId, hintId) || undefined}
    >
      <legend className="mb-1 flex items-center gap-2 p-0 text-label text-ink">
        {label}
        {/* The status glyph sits on the legend rather than beside an option,
            because the state belongs to the whole group, not to one radio.
            aria-hidden throughout: the state is already announced through
            aria-invalid and aria-busy on the fieldset, and repeating it as an
            icon label would double up for a screen-reader user. */}
        {isLoading ? (
          <CircleNotch className="animate-spin text-ink-faint" size={14} aria-hidden />
        ) : resolvedState === "success" ? (
          <CheckCircle className="text-ok" size={14} weight="regular" aria-hidden />
        ) : resolvedState === "error" ? (
          <WarningCircle className="text-err" size={14} weight="regular" aria-hidden />
        ) : null}
      </legend>
      <RadioGroupContext.Provider value={{ name: groupName, value, onValueChange, disabled }}>
        <div
          className={cn(
            "flex gap-3",
            orientation === "vertical" ? "flex-col" : "flex-row flex-wrap gap-x-5",
          )}
        >
          {children}
        </div>
      </RadioGroupContext.Provider>
      {error ? (
        <p id={errorId} className="text-body-sm text-err">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-body-sm text-ink-muted">
          {hint}
        </p>
      ) : null}
    </fieldset>
  )
}

export interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "size"> {
  label: string
  /** Secondary line under the label, e.g. "Recommended for most classes". */
  description?: string
}

/**
 * A single radio option. Usable standalone (pass `name`/`checked`/`onChange`
 * directly, same as a bare native input) or nested inside `RadioGroup`, which
 * supplies `name` and derives `checked` from its own `value` prop — nesting
 * is the expected case, standalone exists for the rare form built one radio
 * at a time from a data-driven list where `RadioGroup`'s children API is
 * awkward.
 *
 * Built on the same `appearance-none` + `:has()` technique as `Checkbox`:
 * the real `<input type="radio">` stays in the accessibility tree, sized and
 * positioned to exactly cover the visible circle, so keyboard/AT behaviour is
 * native and only the paint is custom.
 */
export const Radio = forwardRef<HTMLInputElement, RadioProps>(function Radio(
  { label, description, className, id, name, checked, onChange, disabled, value, ...props },
  ref,
) {
  const group = useContext(RadioGroupContext)
  const generatedId = useId()
  const inputId = id ?? generatedId

  const resolvedName = name ?? group?.name
  const resolvedChecked =
    checked ?? (group && value !== undefined ? group.value === value : undefined)
  const resolvedDisabled = disabled ?? group?.disabled

  return (
    <label
      htmlFor={inputId}
      className={cn(
        "inline-flex cursor-pointer select-none items-start gap-2",
        "has-disabled:cursor-not-allowed has-disabled:opacity-50",
        className,
      )}
    >
      <span
        className={cn(
          "relative mt-0.5 inline-flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full border border-rule bg-paper-raised",
          "transition-colors duration-[var(--dur-instant)] ease-out-soft",
          "hover:border-rule-strong has-checked:border-accent has-checked:hover:border-accent-hover",
          "has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-focus-ring",
        )}
      >
        <input
          ref={ref}
          type="radio"
          id={inputId}
          name={resolvedName}
          value={value}
          checked={resolvedChecked}
          disabled={resolvedDisabled}
          onChange={(event) => {
            onChange?.(event)
            if (group?.onValueChange && value !== undefined) {
              group.onValueChange(String(value))
            }
          }}
          className="peer absolute inset-0 m-0 h-full w-full cursor-pointer appearance-none rounded-full disabled:cursor-not-allowed"
          {...props}
        />
        <span
          aria-hidden
          className="pointer-events-none hidden h-2 w-2 rounded-full bg-accent peer-checked:block"
        />
      </span>
      <span className="flex flex-col">
        <span className="text-body-md text-ink">{label}</span>
        {description ? <span className="text-body-sm text-ink-muted">{description}</span> : null}
      </span>
    </label>
  )
})

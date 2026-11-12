import { forwardRef, useId, useState, type ButtonHTMLAttributes } from "react"
import { CircleNotch } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import type { FieldState } from "@/components/ui/input"

export interface SwitchProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange" | "type"> {
  label: string
  /** Secondary line under the label, e.g. "Email me a weekly digest". */
  description?: string
  /** Controlled checked value. Omit for an uncontrolled switch. */
  checked?: boolean
  defaultChecked?: boolean
  onCheckedChange?: (checked: boolean) => void
  state?: FieldState
  error?: string
  wrapperClassName?: string
  /** `inline` (default): switch, then its label. `row`: label and
   * description on the start side, switch on the end side, for settings
   * rows where every control lines up on one edge. */
  layout?: "inline" | "row"
}

/**
 * A `role="switch"` button rather than a styled native checkbox — unlike
 * `Checkbox`/`Radio`, a switch's semantics ("on/off, takes effect
 * immediately") genuinely differ from a checkbox's ("selected, applies on
 * submit"), and ARIA gives that distinction its own role rather than
 * overloading `checkbox`. State is `aria-checked` on the button itself, so
 * AT announces "switch, on/off" without any extra labelling work here.
 *
 * The thumb only moves via `transform: translateX`, never a `left`/`right`
 * position change (DESIGN.md §9.2: animate transform/opacity only), and the
 * RTL flip is handled with the `rtl:` variant rather than swapping start/end
 * offsets, because a translated distance has no logical-property form to
 * begin with — `rtl:` on the transform utility is the correct primitive.
 */
export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  {
    label,
    description,
    checked,
    defaultChecked,
    onCheckedChange,
    state,
    error,
    disabled,
    className,
    wrapperClassName,
    layout = "inline",
    id,
    ...props
  },
  ref,
) {
  const generatedId = useId()
  const switchId = id ?? generatedId
  const descId = description ? `${switchId}-desc` : undefined
  const errorId = error ? `${switchId}-error` : undefined

  const [uncontrolledChecked, setUncontrolledChecked] = useState(defaultChecked ?? false)
  const isControlled = checked !== undefined
  const isChecked = isControlled ? checked : uncontrolledChecked

  const resolvedState: FieldState | undefined = error ? "error" : state
  const isLoading = resolvedState === "loading"
  const isDisabled = disabled || isLoading

  function handleClick() {
    if (isDisabled) return
    const next = !isChecked
    if (!isControlled) setUncontrolledChecked(next)
    onCheckedChange?.(next)
  }

  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      <div
        className={cn(
          "flex items-start gap-3",
          layout === "row" && "flex-row-reverse justify-between gap-6",
        )}
      >
        <button
          ref={ref}
          type="button"
          role="switch"
          id={switchId}
          aria-checked={isChecked}
          aria-describedby={cn(errorId, descId) || undefined}
          aria-invalid={resolvedState === "error" || undefined}
          aria-busy={isLoading || undefined}
          disabled={isDisabled}
          onClick={handleClick}
          className={cn(
            "relative inline-flex h-6 w-10 flex-none cursor-pointer items-center rounded-full border",
            "transition-colors duration-[var(--dur-instant)] ease-out-soft active:scale-[0.98]",
            "disabled:cursor-not-allowed disabled:opacity-50",
            isChecked ? "border-primary bg-primary" : "border-outline-variant bg-surface-container-low",
            resolvedState === "error" && "border-error",
            resolvedState === "success" && "border-success",
            className,
          )}
          {...props}
        >
          <span
            aria-hidden
            className={cn(
              "inline-flex h-4 w-4 flex-none items-center justify-center rounded-full bg-surface-container-lowest",
              "transition-transform duration-[var(--dur-instant)] ease-out-soft",
              isChecked ? "translate-x-[18px] rtl:-translate-x-[18px]" : "translate-x-1 rtl:-translate-x-1",
            )}
          >
            {isLoading ? (
              <CircleNotch aria-hidden className="h-3 w-3 animate-spin text-on-surface-variant" />
            ) : null}
          </span>
        </button>
        {/* `<label for>` works on a `<button>` per the HTML spec, so clicking
            the text toggles the switch without any extra click handler. */}
        <label
          htmlFor={switchId}
          className={cn(
            "flex flex-col select-none",
            isDisabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
          )}
        >
          <span className="text-body-md text-on-surface">{label}</span>
          {description ? (
            <span id={descId} className="text-body-sm text-on-surface-variant">
              {description}
            </span>
          ) : null}
        </label>
      </div>
      {error ? (
        <p id={errorId} className="text-body-sm text-error">
          {error}
        </p>
      ) : null}
    </div>
  )
})

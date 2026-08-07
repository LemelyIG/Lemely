import type { InputHTMLAttributes } from "react"
import { Check } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * C-14 · Checkbox — not named in UI-spec §4's C-1..C-13 catalogue; added in
 * P3.8 chunk b because T-07's bulk-approve ("Bulk-approve for the trivially
 * fine ones") needs a real multi-select control and nothing in the existing
 * library provides one.
 *
 * A native `<input type="checkbox">` under the hood — keyboard (Space
 * toggles) and AT semantics (checked state announced natively) come for
 * free — with only the visual box swapped in via `appearance-none` and a
 * `:has()` state (Tailwind's `has-*`/bracket variants) driving the checked
 * fill on its wrapping box, so the real input stays in the accessibility
 * tree (no `display:none`/`sr-only` hiding a control AT still needs to
 * find). Caller must supply either a visible `label` or its own
 * `aria-label` — this component renders no default text.
 */

export interface CheckboxProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Visible label rendered beside the box. Omit and pass `aria-label` for a
   * checkbox whose row already carries the label (e.g. a table cell). */
  label?: string
}

export function Checkbox({ className, label, ...props }: CheckboxProps) {
  return (
    <label
      className={cn(
        "inline-flex items-center gap-2 cursor-pointer select-none",
        props.disabled && "cursor-not-allowed opacity-50",
        className,
      )}
    >
      <span
        className={cn(
          "relative inline-flex h-[18px] w-[18px] flex-none items-center justify-center rounded-[4px] border border-border bg-surface transition-colors",
          "has-checked:bg-accent has-checked:border-accent",
          "has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-accent",
        )}
      >
        <input
          type="checkbox"
          className="peer absolute inset-0 h-full w-full m-0 cursor-pointer appearance-none rounded-[4px] disabled:cursor-not-allowed"
          {...props}
        />
        <Check
          weight="bold"
          aria-hidden
          className="pointer-events-none hidden h-3 w-3 text-accent-on peer-checked:block"
        />
      </span>
      {label ? <span className="text-[12.5px] text-t2">{label}</span> : null}
    </label>
  )
}

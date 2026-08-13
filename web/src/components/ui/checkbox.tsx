import { forwardRef, type InputHTMLAttributes } from "react"
import { Check, CircleNotch, Minus } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import type { FieldState } from "@/components/ui/input"

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
 *
 * Restyled onto the Study Notebook tokens (DESIGN.md §3, §12): `border`/
 * `bg`/`text` now come from `--rule` / `--paper-raised` / `--ink-muted`
 * rather than the build-era compatibility names, and the focus ring is
 * `--focus-ring` (blue, "the browser is talking to you") rather than
 * `--accent` — DESIGN.md §3.9 is explicit that focus must stay
 * distinguishable from the accent's own checked-state fill, which the old
 * `outline-accent` here did not.
 */

export interface CheckboxProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Visible label rendered beside the box. Omit and pass `aria-label` for a
   * checkbox whose row already carries the label (e.g. a table cell). */
  label?: string
  /**
   * Renders the box as a dash instead of a tick, for a "select all" control
   * whose children are partly, not fully, selected. Purely visual — the
   * underlying input's `checked` value is unaffected, so callers still drive
   * `checked`/`onChange` themselves.
   */
  indeterminate?: boolean
  /** Async/validation state layered on top of the native `checked` value. */
  state?: FieldState
  /** Inline validation message, rendered under the control. */
  error?: string
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { className, label, indeterminate, state, error, disabled, ...props },
  ref,
) {
  const resolvedState: FieldState | undefined = error ? "error" : state
  const isLoading = resolvedState === "loading"

  return (
    <div className="inline-flex flex-col gap-1">
      <label
        className={cn(
          "inline-flex cursor-pointer select-none items-center gap-2",
          // `has-disabled:` (`:has(:disabled)`), not `props.disabled`, because a
          // checkbox is just as often disabled by an ancestor `<fieldset disabled>`
          // as by its own prop — and in that case React never passes `disabled`
          // down, so a prop-keyed rule renders a fully-active-looking control that
          // cannot be operated. `appearance-none` means the browser draws no
          // disabled affordance of its own here, so this rule is the only one.
          // P4.9 chunk C: S-20 had worked around the gap with `opacity-50` on the
          // whole enclosing Card, which dimmed that card's heading and prose too
          // and put them at 2.28:1 — a serious axe violation. Dimming the label of
          // a genuinely disabled control is exempt from WCAG 1.4.3; dimming a
          // section heading is not.
          "has-disabled:cursor-not-allowed has-disabled:opacity-50",
          className,
        )}
      >
        <span
          className={cn(
            "relative inline-flex h-[18px] w-[18px] flex-none items-center justify-center rounded-sm border border-rule bg-paper-raised",
            "transition-colors duration-[var(--dur-instant)] ease-out-soft",
            "hover:border-rule-strong has-checked:border-accent has-checked:bg-accent has-checked:hover:border-accent-hover has-checked:hover:bg-accent-hover",
            "has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-focus-ring",
            resolvedState === "error" && "border-err",
            resolvedState === "success" && "border-ok",
            indeterminate && "border-accent bg-accent",
          )}
        >
          <input
            ref={ref}
            type="checkbox"
            disabled={disabled || isLoading}
            className="peer absolute inset-0 m-0 h-full w-full cursor-pointer appearance-none rounded-sm disabled:cursor-not-allowed"
            {...props}
          />
          {isLoading ? (
            <CircleNotch
              weight="regular"
              aria-hidden
              className="pointer-events-none h-3 w-3 animate-spin text-ink-faint"
            />
          ) : indeterminate ? (
            <Minus
              weight="bold"
              aria-hidden
              className="pointer-events-none h-3 w-3 text-accent-on"
            />
          ) : (
            <Check
              weight="bold"
              aria-hidden
              className="pointer-events-none hidden h-3 w-3 text-accent-on peer-checked:block"
            />
          )}
        </span>
        {label ? <span className="text-body-sm text-ink-muted">{label}</span> : null}
      </label>
      {error ? <p className="text-body-sm text-err">{error}</p> : null}
    </div>
  )
})

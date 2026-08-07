import { Check } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * C-15 · Stepper — not named in UI-spec §4's C-1..C-13 catalogue; added in
 * P3.8 chunk c because T-09's six-step quiz builder needs a real
 * step-navigation control and nothing else in the library provides one.
 * Follows C-14 Checkbox's precedent (P3.8 chunk b) for adding a genuinely
 * missing cross-cutting primitive here rather than a one-off in the screen
 * file, since a stepper is a plausible need for future multi-step flows
 * (P4 onboarding, placement test).
 *
 * Every step is a real, focusable `<button>` and always reachable — the
 * builder does not gate which steps a teacher may jump to (a draft's
 * fields are all independently PATCHable; revisiting an earlier step to
 * change a decision is a normal flow, not a broken one). Navigation stays
 * enabled even once a quiz is read-only: "read-only" means each step's own
 * form controls can't be edited, not that the step *navigation* itself goes
 * away — a teacher must still be able to browse what was configured.
 * `disabled` (unused by the quiz builder today, kept for a future
 * read-only-*everything* flow) swaps every button for a plain `<span>`.
 */

export interface StepperStep {
  id: number
  label: string
}

export interface StepperProps {
  steps: StepperStep[]
  current: number
  onSelect: (id: number) => void
  /** Steps whose fields already carry a value — rendered with a check mark
   * instead of a number. Purely a "you've touched this" hint, never a gate
   * on navigation. */
  completed?: Set<number>
  /** Read-only: renders a plain, non-interactive step indicator (no
   * buttons) — used for a non-draft quiz, where nothing here can be edited. */
  disabled?: boolean
}

export function Stepper({ steps, current, onSelect, completed, disabled }: StepperProps) {
  return (
    <nav aria-label="Quiz builder steps">
      <ol className="flex flex-wrap items-center gap-1.5 list-none m-0 p-0">
        {steps.map((step) => {
          const active = step.id === current
          const done = (completed?.has(step.id) ?? false) && !active
          const glyph = (
            <span
              aria-hidden="true"
              className={cn(
                "flex h-6 w-6 flex-none items-center justify-center rounded-full font-mono text-[11px]",
                active
                  ? "bg-ink text-accent-on"
                  : done
                    ? "bg-accent-subtle text-accent"
                    : "bg-surface-2 text-t3",
              )}
            >
              {done ? <Check weight="bold" className="h-3 w-3" /> : step.id}
            </span>
          )
          const label = (
            <span className={cn("text-[12.5px] whitespace-nowrap", active ? "text-t1 font-medium" : "text-t2")}>
              {step.label}
            </span>
          )
          return (
            <li key={step.id} className="flex items-center gap-1.5">
              {disabled ? (
                <span
                  aria-current={active ? "step" : undefined}
                  className="flex items-center gap-2 px-2.5 py-1.5"
                >
                  {glyph}
                  {label}
                </span>
              ) : (
                <button
                  type="button"
                  aria-current={active ? "step" : undefined}
                  onClick={() => onSelect(step.id)}
                  className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg cursor-pointer hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  {glyph}
                  {label}
                </button>
              )}
              {step.id < steps.length ? (
                <span aria-hidden="true" className="w-4 h-px bg-border flex-none" />
              ) : null}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

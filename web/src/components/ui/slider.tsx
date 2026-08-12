import type { InputHTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * C-16 · Slider — not named in the UI-spec §4 C-1..C-13 catalogue; added in
 * P4.8 chunk A because S-02's weekly-study-time and per-topic confidence
 * questions ("How confident are you in algebra?") both need a real range
 * input and nothing in the library provided one. Follows C-14/C-15's
 * precedent for adding a genuinely missing cross-cutting primitive here
 * rather than inlining it in a screen file (the legacy `Onboarding.tsx` had
 * an inline `<input type="range">` with no shared styling — this replaces
 * that one-off).
 *
 * A native `<input type="range">` under the hood (keyboard — arrow keys,
 * Home/End — and AT semantics come for free) with only the track/thumb
 * repainted via `accent-*`, matching DESIGN.md's "Input Fields" guidance
 * (surface fill, border shifts to primary on focus doesn't apply to a
 * native range thumb, so focus is carried by the shared
 * `focus-visible:outline-accent` ring instead, consistent with every other
 * interactive control in the library). The wrapping `py-9px` gives the thumb
 * a >=44px vertical hit target on touch per QUALITY-BAR's touch-target rule,
 * without inflating the visible track height past DESIGN.md's 6px meter
 * rhythm.
 *
 * Deliberately does NOT own a "skipped" state — S-02's skip affordance is a
 * screen-level decision (a visible "Skip" action next to the question,
 * D4.5), not something baked into this primitive. The caller renders the
 * slider once the student has a value to show; before that, the caller
 * shows its own unanswered affordance instead of mounting this component at
 * a fabricated default position (rule: a skipped answer must never render as
 * an answer the student gave).
 */

export interface SliderProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange"> {
  value: number
  onValueChange: (value: number) => void
  min: number
  max: number
  step?: number
  /** Required accessible name stating what this slider measures (e.g.
   * "Weekly study hours" or "Confidence in 4.3 Electric circuits"). */
  "aria-label": string
}

export function Slider({
  value,
  onValueChange,
  min,
  max,
  step = 1,
  className,
  ...props
}: SliderProps) {
  return (
    <div className={cn("py-9px", className)}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onValueChange(Number(event.target.value))}
        className="w-full h-1.5 cursor-pointer appearance-none rounded-full bg-surface-2 accent-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        {...props}
      />
    </div>
  )
}

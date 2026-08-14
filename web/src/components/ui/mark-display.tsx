/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"
import { CountUp } from "./celebration"

/*
 * C-2 Mark display. "58 / 80" plus percentage, in the two scales the product
 * needs it at: hero (results overview — "the mark is the hero" per
 * LEMELY_UI_SPEC 1.6) and inline (list rows, question rows, subject cards).
 * Numeric figures use JetBrains Mono. DESIGN.md §4 reserves mono for exactly
 * this: "All scores, grades, marks, XP, timers, paper codes, IDs. Always
 * tabular-nums."
 *
 * P4.2 CORRECTED THE HERO SIZE, which is the one that mattered most and was
 * the one that was wrong. This component applied the mono rule at the inline
 * size only, and rendered the hero — the largest number in the product, the
 * score a student comes to this screen to read — as `display-hero`, i.e.
 * 60px Newsreader. Its own docstring stated the rule while the code broke it
 * on the one call site the rule was written for.
 *
 * Same shape as D4.1's `--font-serif` finding: a well-formed utility quietly
 * resolving to the wrong face, invisible to every gate, because the token
 * discipline gate greps for raw values bypassing the token block and this was
 * not a raw value. §4.2's `data-lg` rung is the specified treatment for "the
 * big number: a score, a predicted grade", and it is 32px, not 60px.
 */

export interface MarkDisplayProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  awarded: number
  available: number
  size?: "hero" | "inline"
  /**
   * Count the mark up from zero as it lands — §9.3's "marked-paper result
   * reveal", the one moment in this product where a number genuinely arrives
   * while the reader is watching it.
   *
   * **Only ever true on the live marking path.** A student who opens the same
   * paper again from their history is looking at a mark that has been true
   * since they closed the tab, and animating it there would stage an event
   * that already happened. `PaperResult` passes this from its `live` flag and
   * nowhere else.
   *
   * **There is deliberately no flourish here, at any mark.** Confetti would
   * require the product to decide a mark is good, and it has no honest basis
   * for that: a threshold would mean its absence reads as disappointment, and
   * §9.3 rules celebration out on a dropped mark outright. The count-up is
   * legible drama for a number the student has been waiting for, not a verdict
   * on it. Hero size only — an inline mark in a history row is not an arrival.
   */
  reveal?: boolean
  showPercent?: boolean
}

export function MarkDisplay({
  awarded,
  available,
  size = "inline",
  showPercent = true,
  reveal = false,
  className,
  ...props
}: MarkDisplayProps) {
  const pct = available > 0 ? Math.round((awarded / available) * 100) : 0

  if (size === "hero") {
    return (
      <div
        className={cn("flex items-baseline gap-2.5", className)}
        aria-label={`${awarded} out of ${available} marks, ${pct} percent`}
        {...props}
      >
        <span className="text-data-lg text-ink">
          {reveal ? <CountUp value={awarded} from={0} /> : awarded}
        </span>
        <span className="text-data-md text-ink-faint">/ {available}</span>
        {showPercent && (
          // `ms-1`, not `ml-1`: the percentage trails the mark and must stay
          // trailing under `dir="rtl"` (P3.4).
          <span className="text-data-sm text-ink-muted bg-paper-sunk rounded-full px-2.5 py-1 ms-1">
            {pct}%
          </span>
        )}
      </div>
    )
  }

  return (
    <div
      className={cn("inline-flex items-baseline gap-1.5", className)}
      aria-label={`${awarded} out of ${available} marks, ${pct} percent`}
      {...props}
    >
      <span className="text-data-md text-ink">
        {awarded}/{available}
      </span>
      {showPercent && <span className="text-data-sm text-ink-faint">{pct}%</span>}
    </div>
  )
}

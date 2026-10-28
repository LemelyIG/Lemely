/* Hallmark · pre-emit critique: P4 H4 E5 S4 R5 V3 — one star and a number, never five stars; the sentence label is read once and the glyph is hidden from assistive technology. */
import { Star } from "@phosphor-icons/react"
import { Chip } from "@/components/ui/chip"
import { cn } from "@/lib/utils"
import { ratingDisplay } from "@/lib/tutoring/ratingLabel"
import type { Rating } from "@/lib/tutoringTypes"

/*
 * C-22 Rating summary (SPEC §d, decision-log row 6). "4.6 · 12 students" with a
 * single star glyph, or a "New" pill while fewer than three students have rated
 * the tutor. Never a row of five stars: a row of stars says "this is precise",
 * and a rating from a handful of students is not.
 *
 * The whole indicator is one labelled image with a full-sentence name ("Rated
 * 4.6 out of 5 by 12 students."), and its visible parts are hidden from
 * assistive technology so the sentence is read once. The wording and the
 * "New" threshold are in `lib/tutoring/ratingLabel.ts`.
 */

export interface RatingSummaryProps {
  rating: Rating
  className?: string
}

export function RatingSummary({ rating, className }: RatingSummaryProps) {
  const display = ratingDisplay(rating)

  if (display.kind === "new") {
    return (
      <Chip tone="neutral" role="img" aria-label={display.ariaLabel} className={className}>
        <span aria-hidden>{display.text}</span>
      </Chip>
    )
  }

  return (
    <span
      role="img"
      aria-label={display.ariaLabel}
      className={cn("inline-flex items-center gap-1.5 text-data-md text-ink", className)}
    >
      <Star size={16} weight="fill" className="text-pastel-amber-ink" aria-hidden />
      <span aria-hidden>{display.text}</span>
    </span>
  )
}

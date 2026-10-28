/*
 * C-22 · how a tutor's rating is worded (SPEC §d, §i.4, decision-log row 6).
 *
 * "4.6 · 12 students" once three students have rated a tutor, and the word
 * "New" before that; never stars for a handful of ratings. The server decides
 * `state`, but this module does not take a number on trust: a "rated" rating
 * with no average, or with fewer than three students, is shown as New, because
 * showing 5.0 from one review is the claim the threshold exists to prevent.
 *
 * The accessible name is a whole sentence. A star glyph and a bare "4.6" read
 * out as "star 4.6 dot 12 students" otherwise.
 */

import type { Rating } from "@/lib/tutoringTypes"

/** Fewer distinct students than this and the tutor is shown as New. */
export const MIN_RATED_STUDENTS = 3

export interface RatingDisplay {
  kind: "new" | "rated"
  /** What is drawn: "4.6 · 12 students", or "New". */
  text: string
  /** "12 students", "1 student". Always set, from `count`. */
  countText: string
  /** The value alone, one decimal: "4.6". Absent for New. */
  average?: string
  /** One full sentence for the whole indicator. */
  ariaLabel: string
}

function students(count: number): string {
  return `${count} ${count === 1 ? "student" : "students"}`
}

export function ratingDisplay(rating: Rating): RatingDisplay {
  const countText = students(rating.count)
  const isNew =
    rating.state === "new" || rating.average === null || rating.count < MIN_RATED_STUDENTS

  if (isNew || rating.average === null) {
    return {
      kind: "new",
      text: "New",
      countText,
      ariaLabel: `New tutor. Fewer than ${MIN_RATED_STUDENTS} students have rated this tutor so far.`,
    }
  }

  const average = rating.average.toFixed(1)
  return {
    kind: "rated",
    text: `${average} · ${countText}`,
    countText,
    average,
    ariaLabel: `Rated ${average} out of 5 by ${countText}.`,
  }
}

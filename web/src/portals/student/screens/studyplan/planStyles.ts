/*
 * Token-only colour maps for the study plan's activity tiles (`.sic`: 40px,
 * radius 13px). No new tokens. Subject dots are not here: they come from the
 * kit's `SubjectDot`, which colours by subject so a subject keeps one colour on
 * every screen.
 */

export const ACTIVITY_TILE: Record<string, string> = {
  practice: "bg-primary-container text-primary",
  flashcards: "bg-secondary-container text-on-secondary-container",
  past_paper: "bg-success-container text-success-text",
  review: "bg-surface-container-high text-on-surface-variant",
}

export const DONE_TILE = "bg-success-container text-success-text"

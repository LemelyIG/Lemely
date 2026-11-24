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

/**
 * The one primary action of a state or a sheet (`.big4`: 54px, radius 18, 16px). The height is
 * `h-`, not `min-h-`: on a touch screen the global `(pointer: coarse)` rule sets an unlayered
 * `min-block-size: 44px` on every button, which beats any `min-h-*` utility and left this
 * button at 44px on a phone.
 */
export const CTA = "h-[54px] w-full rounded-[18px] px-7 text-[16px] font-bold shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)]"

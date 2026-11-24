// The flashcards primary button, once. Mock t.css `.btn.big4` plus pr.css `.go2[disabled]` and fc.css `.btn.dgo`.
// !min-h-[54px]: the coarse-pointer floor in index.css is unlayered and would otherwise cap a phone button at 44px.

export const FOCUS = "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

const SOLID =
  "!min-h-[54px] w-full rounded-[18px] px-7 text-[16px] font-bold text-on-primary shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)] disabled:cursor-not-allowed disabled:bg-surface-container-high disabled:text-on-surface-variant disabled:shadow-none"

/** Every solid action in the flashcards lane: Show answer, Back to decks, Make cards, Save, Try again. */
export const PRIMARY_BTN = `${SOLID} bg-primary ${FOCUS}`

/** The same button for a deck or card delete. */
export const DANGER_BTN = `${SOLID} bg-on-error-container ${FOCUS}`

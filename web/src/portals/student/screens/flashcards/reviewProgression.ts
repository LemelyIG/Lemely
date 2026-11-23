/** A card may be rated once, after its answer has been revealed. */
export function canGradeCard(cardId: string | null, revealed: boolean, graded: ReadonlySet<string>): boolean {
  return cardId !== null && revealed && !graded.has(cardId)
}

type Closest<T> = { closest?: (selector: string) => T | null } | null | undefined

/** Ignore shortcuts inside editable controls, including editable descendants. */
export function isEditableTarget(target: Closest<unknown>): boolean {
  return Boolean(target?.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"])'))
}

/**
 * Space and Enter belong to whatever button or link has focus (End review, Retry, Back). The review's
 * own controls carry `data-review-primary` and are the only ones whose Space/Enter flips the card.
 */
export function isForeignControl(target: Closest<{ hasAttribute: (name: string) => boolean }>): boolean {
  const control = target?.closest?.('button, a, summary, [role="button"]')
  return Boolean(control) && !control?.hasAttribute("data-review-primary")
}

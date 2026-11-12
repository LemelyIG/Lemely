/*
 * Pure logic behind `CodeInput.tsx` (review round 1, Important finding 1).
 * No React, no DOM — the same split every `*Logic.ts` module in this repo
 * uses, and for the same reason: `vitest.config.ts` runs the unit suite in a
 * Node environment with no jsdom (D3.20), so `codeInputLogic.test.ts`
 * exercises this directly.
 *
 * ── Why this file exists at all ──────────────────────────────────────────
 *
 * The first cut of `CodeInput` represented its six boxes as a single joined
 * `value: string`, reconstructing the per-box array on every render via
 * `value[i] ?? ""`. That representation cannot hold an empty box before a
 * filled one: `["1","2","","4","5","6"].join("")` is `"12456"`, five
 * characters, and re-splitting *that* back into six boxes on the next render
 * shifts every digit after the gap one place left. Backspacing a middle
 * digit — or clicking into an empty box out of typing order — silently
 * mangled whatever the reader had actually typed, with no error and no test
 * to catch it (the component itself is unrenderable under this project's
 * node-only vitest config, per its own module note).
 *
 * The fix is to never round-trip positions through a compacted string.
 * Every function below takes and returns a `Digits` array — one slot per
 * box, a real empty string standing for an empty box, no gap-collapsing
 * anywhere — and `CodeInput.tsx` holds that array as its own state, joining
 * it into a string only at the boundary, to notify a caller of the current
 * value. `ParentLogin.tsx`'s original `CodeStep` held its `digits` the same
 * way, in its parent's `useState<string[]>`; this module is that same shape,
 * pulled out so it can be tested independently of any component tree.
 */

export type Digits = string[]

/** Split an initial `value` into a `length`-box array, the one place a
 * string ever becomes a `Digits` — used only for a fresh mount's starting
 * state, never for an update. Shorter than `length`, this pads with empty
 * boxes; a caller resetting the code mid-flow should remount `CodeInput`
 * with a fresh `key` rather than expect this to resync a live array. */
export function digitsFromValue(value: string, length: number): Digits {
  return Array.from({ length }, (_, i) => value[i] ?? "")
}

/** One box's typed input, applied to the array in place. `raw` is whatever
 * the input fired (which can be more than one character on some IME/mobile
 * keyboards, hence the `slice(-1)` — the last character typed wins). Reports
 * which box should receive focus next: the one after `index`, but only when
 * an actual digit landed and there is a next box — advancing on a cleared
 * box would make backspace jump the caret past the box the reader just
 * emptied. */
export function applyDigitChange(
  digits: Digits,
  index: number,
  raw: string,
): { digits: Digits; focusIndex: number } {
  const char = raw.replace(/\D/g, "").slice(-1)
  const next = [...digits]
  next[index] = char
  const focusIndex = char && index < digits.length - 1 ? index + 1 : index
  return { digits: next, focusIndex }
}

/**
 * Backspace on box `index`. Only ever clears the *previous* box and moves
 * focus there — matching the original `CodeStep` behaviour exactly: pressing
 * Backspace on a box that already holds a digit is left to the browser's own
 * native single-character deletion (the box's `onChange` fires from that),
 * this function only handles the "box is already empty, step back" case.
 * Returns `null` for a no-op (the box has a digit, or there is no previous
 * box), so the caller can skip re-rendering entirely.
 */
export function applyBackspace(
  digits: Digits,
  index: number,
): { digits: Digits; focusIndex: number } | null {
  if (digits[index] || index === 0) return null
  const next = [...digits]
  next[index - 1] = ""
  return { digits: next, focusIndex: index - 1 }
}

/**
 * A paste event's clipboard text, distributed across every box from
 * position 0 — a reader copying the whole code from an email client or a
 * password manager pastes it into whichever box happens to be focused, and
 * dropping all but the last character into that one box (the native
 * single-character-input behaviour) would silently discard the rest.
 * Returns `null` when the pasted text contains no digit at all, so the
 * caller can leave the native paste behaviour alone rather than clearing the
 * boxes for a stray non-numeric clipboard.
 */
export function applyPaste(
  length: number,
  pastedRaw: string,
): { digits: Digits; focusIndex: number } | null {
  const pasted = pastedRaw.replace(/\D/g, "").slice(0, length)
  if (!pasted) return null
  const digits = Array.from({ length }, (_, i) => pasted[i] ?? "")
  return { digits, focusIndex: Math.min(pasted.length, length - 1) }
}

/** Whether every box holds a character — `CodeInput`'s own signal to fire
 * `onComplete` once, not on every edit. */
export function isCodeComplete(digits: Digits): boolean {
  return digits.length > 0 && digits.every((digit) => digit !== "")
}

/** The one place a `Digits` array becomes a string again, for notifying a
 * caller of the current value via `onChange`/`onComplete`. Never fed back
 * into `digitsFromValue` to reconstruct component state — that round trip
 * is exactly the bug this module exists to rule out. */
export function joinDigits(digits: Digits): string {
  return digits.join("")
}

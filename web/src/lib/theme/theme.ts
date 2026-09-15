/*
 * Theme preference (Phase C, task C5b): the pure decision table behind the
 * Appearance setting (`useTheme.ts`) and the flash-free pre-mount init
 * (`public/shell-init.js`, which implements this exact same three-way table
 * inline in plain ES5, because it runs before any bundle exists and cannot
 * import this module — see that file's own comment). `themeInit.test.ts`
 * pins the two against each other so they cannot silently disagree.
 */

/** What the reader chose. "system" is the default — no explicit choice made
 * yet, or one that was cleared — and means "follow the OS". */
export type ThemePreference = "system" | "light" | "dark"

/** What actually paints, once "system" has been resolved against the
 * device's `prefers-color-scheme`. `index.css`'s `data-theme` attribute (and
 * nothing else — there is deliberately no `prefers-color-scheme` media query
 * in that file, see `themeInit.test.ts`) takes one of these two values. */
export type ResolvedTheme = "light" | "dark"

/** The `localStorage` key the preference is persisted under. A device
 * preference, not session data — `lib/auth/storage.ts`'s `endSession` does
 * not clear it; see that function's own comment. */
export const THEME_STORAGE_KEY = "lemely.theme"

/** Narrows an arbitrary value to `ThemePreference`. The single source of
 * truth for what counts as valid, so `readThemePreference` below and any
 * future caller (the settings UI validating a value before writing it) agree
 * by construction rather than by two hand-written lists staying in sync. */
export function isThemePreference(x: unknown): x is ThemePreference {
  return x === "system" || x === "light" || x === "dark"
}

/**
 * Reads a raw `localStorage` value into a `ThemePreference`, defaulting to
 * `"system"` for anything invalid: `null` (nothing stored yet), a value a
 * future version of this product might write for a preference that doesn't
 * exist yet, or plain garbage (a reader's own devtools experiment, a
 * corrupted write). A stored value this app itself may not have written
 * should never crash the app or silently resolve to "dark" instead of
 * falling back to following the OS.
 */
export function readThemePreference(raw: string | null): ThemePreference {
  return isThemePreference(raw) ? raw : "system"
}

/**
 * The three-way table: `"system"` resolves against the OS signal;
 * `"light"`/`"dark"` are already resolved and ignore `systemPrefersDark`
 * entirely — an explicit choice always wins over the device.
 */
export function resolveTheme(pref: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (pref === "system") return systemPrefersDark ? "dark" : "light"
  return pref
}

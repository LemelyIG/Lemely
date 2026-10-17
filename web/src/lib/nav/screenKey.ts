/*
 * What identifies "a different screen" for the entrance animation
 * `ScreenOutlet`/`ScreenFrame` play (`.lm-screen`'s `lm-in`, DESIGN.md §9).
 *
 * The obvious answer — `location.key`, one per history entry — is wrong,
 * because not every history entry is a new screen. `useDialogHistory` opens
 * an overlay by pushing an entry at the URL the reader is already on, and
 * `react-router`'s `navigate()` reduces the `Location` it is handed to a path
 * string inside `normalizeTo` before `createLocation` runs, so `createLocation`
 * has no key left to carry over and mints a fresh one. Same URL, new key.
 *
 * Keyed on that, the wrapper remounted its whole subtree the instant any
 * overlay tried to open — destroying the `useState` in the screen that had
 * just been set to "this dialog is open", so screen-local dialogs could not
 * appear at all. Keyed on the URL instead, a same-URL push is correctly not a
 * new screen, and a real navigation still is.
 *
 * Sibling of `scrollRestorationKey`, and for the same reason: an expression
 * this load-bearing belongs somewhere a Node unit test can reach it, not
 * inline in a component the test runner cannot render (D3.20).
 */
export function screenKey(location: { pathname: string; search: string }): string {
  return location.pathname + location.search
}

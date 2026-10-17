/*
 * Packet B2a · shared "what does back mean here" decision for `BackControl`
 * and, later, Task 4's edge-swipe-back.
 *
 * `window.history.state?.idx` is react-router's own entry index within this
 * tab's history stack (it stamps one onto every entry it creates). A value
 * greater than zero means there is somewhere in *this tab's* history to go
 * back to, so `navigate(-1)` is both correct and preserves scroll
 * restoration. An index of exactly zero — or no index at all, which is what
 * a deep link followed directly (a bookmark, a shared link, a fresh PWA
 * launch) leaves in place — means `navigate(-1)` would leave the app
 * entirely (or land outside it, on whatever page opened this tab), so the
 * control falls back to a fixed, known-good route instead.
 */

export function backTarget(
  historyIdx: number | null | undefined,
  fallback: string,
): { kind: "history" } | { kind: "route"; to: string } {
  if (typeof historyIdx === "number" && historyIdx > 0) {
    return { kind: "history" }
  }
  return { kind: "route", to: fallback }
}

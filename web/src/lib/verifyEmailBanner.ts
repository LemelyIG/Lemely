/*
 * When the verify-email banner appears, and in which of its two forms.
 *
 * Split out of the component for the reason every `*Outcome.ts` module in this
 * codebase exists: the web test runner is `environment: "node"` with no jsdom
 * and collects only `tests/unit/*.test.ts`, so logic inside a component can
 * only be pinned by reading its source, and a source-reading gate cannot tell
 * a rule that works from a rule that merely still has the right words in it.
 *
 * Two things this deliberately does NOT do. It does not read storage (the
 * caller resolves `dismissed` and passes it, so this stays a pure function of
 * its inputs), and it does not treat "unknown" as "unverified" — see
 * `emailVerified` below.
 */

/**
 * The one route where the banner is pinned. Matched exactly, never by prefix:
 * a future `/student/correction-history` would otherwise inherit a
 * non-dismissible banner and a disabled button by accident.
 */
export const CORRECTION_PATH = "/student/correct"

/**
 * - `hidden` — render nothing at all, including no margin.
 * - `dismissible` — the ordinary strip, with a dismiss control.
 * - `pinned` — the same strip with no dismiss control, and any dismissal
 *   already stored for this session ignored.
 */
export type VerifyEmailBannerState = "hidden" | "dismissible" | "pinned"

export function verifyEmailBannerState({
  emailVerified,
  pathname,
  dismissed,
}: {
  /**
   * `undefined` while `useProfile()` is pending, and when it errored. Both
   * mean the app does not know, and not knowing is not the same as knowing
   * the address is unverified: a banner that appears during a load, or
   * because a request failed, tells the reader something the app has not
   * established. Only an explicit `false` shows the banner.
   */
  emailVerified: boolean | undefined
  pathname: string
  dismissed: boolean
}): VerifyEmailBannerState {
  if (emailVerified !== false) return "hidden"
  // Checked before `dismissed` on purpose: this is the screen the gate
  // actually blocks, and the banner is the explanation for the disabled
  // marking button sitting under it.
  if (pathname === CORRECTION_PATH) return "pinned"
  if (dismissed) return "hidden"
  return "dismissible"
}

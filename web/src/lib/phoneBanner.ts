import { type BannerStorage } from "@/lib/verifyEmailDismissal"

/*
 * When the "add your phone number" banner appears (UD-11), and where it sends the reader.
 *
 * The same split as `verifyEmailBanner.ts`, for the same reason: the web runner is
 * `environment: "node"`, so a rule inside the component could only be pinned by reading its source.
 * Two rules differ from the verify-email banner on purpose:
 *
 * - It is never pinned. Nothing a student does is locked for want of a phone number; only paying
 *   needs one, and checkout asks for it inline at that moment. So it is always dismissible.
 * - It steps aside on the profile screen itself, where the number's own card is the prompt and a
 *   strip above it would say the same thing twice.
 */

/** `GET /me/profile` says there is no usable number on file. Only an explicit `true` shows it. */
export type PhoneBannerState = "hidden" | "dismissible"

/**
 * The profile screen for a role. Student and teacher have their own settings section; parent and
 * both admin roles have only the top-level one (see `SettingsLaneRedirect` in `routes.tsx`, which
 * would send a student or teacher on to their own, dropping any `#hash`, so link there directly).
 */
export function profileSettingsPath(role: string | undefined): string {
  if (role === "student") return "/student/settings"
  if (role === "teacher") return "/teacher/settings"
  return "/settings/profile"
}

/** Whether `pathname` is the screen that already holds the phone card. */
export function isProfileSettingsPath(pathname: string): boolean {
  const clean = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
  return clean === "/student/settings" || clean === "/teacher/settings" || clean === "/settings/profile"
}

export function phoneBannerState({
  phoneMissing,
  pathname,
  dismissed,
}: {
  /**
   * `undefined` while `useProfile()` is pending or errored. Not knowing is not the same as the
   * number being missing, so only an explicit `true` shows the banner.
   */
  phoneMissing: boolean | undefined
  pathname: string
  dismissed: boolean
}): PhoneBannerState {
  if (phoneMissing !== true) return "hidden"
  if (isProfileSettingsPath(pathname)) return "hidden"
  if (dismissed) return "hidden"
  return "dismissible"
}

/** `sessionStorage`, like the verify-email banner: the dismissal lasts the visit, and the reminder
 * returns the next time the app is opened, so it needs no clock and no stored timestamp. */
export const PHONE_BANNER_DISMISS_KEY = "lemely:phone-banner-dismissed"
const DISMISSED = "1"

/** False whenever the answer cannot be read, including with no storage at all. */
export function readPhoneBannerDismissed(storage: BannerStorage | undefined): boolean {
  if (!storage) return false
  try {
    return storage.getItem(PHONE_BANNER_DISMISS_KEY) === DISMISSED
  } catch {
    return false
  }
}

/** Silent on failure: the component has already hidden the strip in state. */
export function writePhoneBannerDismissed(storage: BannerStorage | undefined): void {
  if (!storage) return
  try {
    storage.setItem(PHONE_BANNER_DISMISS_KEY, DISMISSED)
  } catch {
    // Deliberately empty: losing the persistence must not break the interaction.
  }
}

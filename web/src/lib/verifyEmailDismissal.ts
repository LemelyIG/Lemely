/*
 * Whether this session has dismissed the verify-email banner.
 *
 * `sessionStorage`, not `localStorage`, and that is the whole of decision D5:
 * the dismissal lasts the visit and the banner returns next time the app is
 * opened. The correction screen enforces the point where it actually matters
 * (it renders the banner un-dismissibly and disables the marking button), so
 * the reminder everywhere else can afford to be gentle, and a dismissal that
 * self-renews needs no stored timestamp, no clock, and no boundary test.
 *
 * The storage is a parameter rather than a global for the reason
 * `StaleChunkGuard` takes one (`lib/staleChunk.ts`): the web test runner is
 * `environment: "node"` with no `sessionStorage` at all, and a module that
 * reached for a global could only be checked by reading its source.
 *
 * Every access is wrapped. Safari private browsing and a full storage quota
 * both make storage throw on `setItem`, and some private-mode configurations
 * throw on `getItem` too. A throw here must never be the reason a portal shell
 * fails to render, so it degrades to "not dismissed": the banner shows.
 * Showing a banner one time too many is a strictly better failure than a blank
 * app.
 */

/** The slice of `Storage` this module uses, so a test can pass a two-method
 * fake rather than implementing the whole interface. */
export type BannerStorage = Pick<Storage, "getItem" | "setItem">

export const VERIFY_EMAIL_DISMISS_KEY = "lemely:verify-email-banner-dismissed"

/** The only value treated as a dismissal. Anything else in the slot (a
 * half-written value, another tool's key collision) reads as not dismissed. */
const DISMISSED = "1"

/** Whether this session has dismissed the banner. False whenever the answer
 * cannot be read, including when there is no storage at all. */
export function readDismissed(storage: BannerStorage | undefined): boolean {
  if (!storage) return false
  try {
    return storage.getItem(VERIFY_EMAIL_DISMISS_KEY) === DISMISSED
  } catch {
    return false
  }
}

/** Record a dismissal for the rest of this session. Silent on failure: the
 * caller has already hidden the banner in component state, so a storage that
 * refuses the write costs only the persistence, not the interaction. */
export function writeDismissed(storage: BannerStorage | undefined): void {
  if (!storage) return
  try {
    storage.setItem(VERIFY_EMAIL_DISMISS_KEY, DISMISSED)
  } catch {
    // Deliberately empty. See the module header.
  }
}

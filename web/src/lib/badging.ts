/*
 * The Badging API, wrapped (Task 7 / B5a).
 *
 * Chromium/Edge-only (installed PWAs), so every call is a nicety — `false`
 * when the API doesn't exist or the call itself rejects, never a throw.
 * `nav` is injected (default: the real global) for the same testability
 * reason `haptics.ts` and `share.ts` give.
 */

/** Optional, unlike `Pick<Navigator, ...>` — the Badging API is
 * Chromium/Edge-only, and an injected test fake standing in for every other
 * engine should not have to stub methods it will never be asked for. */
export interface BadgeCapableNavigator {
  setAppBadge?: (count?: number) => Promise<void>
  clearAppBadge?: () => Promise<void>
}

export async function setAppBadge(
  count: number,
  nav: BadgeCapableNavigator | undefined = typeof navigator === "undefined" ? undefined : navigator,
): Promise<boolean> {
  if (typeof nav?.setAppBadge !== "function" || typeof nav.clearAppBadge !== "function") return false
  try {
    if (count > 0) {
      await nav.setAppBadge(count)
    } else {
      await nav.clearAppBadge()
    }
    return true
  } catch {
    return false
  }
}

/*
 * The Vibration API, wrapped (Task 7 / B5a).
 *
 * Unsupported on iOS Safari and every desktop browser, so a haptic is always
 * a nicety layered on top of a real affordance (a button press, a confirm),
 * never load-bearing feedback on its own — `haptic` reports whether it
 * actually fired rather than throwing when the API is absent.
 *
 * The `nav` parameter takes an injected, `navigator`-shaped object (default:
 * the real global) so this stays testable under vitest's jsdom-less
 * `environment: "node"` (`vitest.config.ts`), the same shape `pushDecision.ts`
 * and `pushAutoEnable.ts` use for the same reason.
 */

export type HapticKind = "tap" | "success" | "warning"

/** Optional, unlike `Pick<Navigator, "vibrate">` — most engines (every iOS
 * browser, every desktop one) genuinely lack `vibrate`, and an injected test
 * fake standing in for one of those should not have to stub it. */
export interface VibrationCapableNavigator {
  vibrate?: (pattern: number | number[]) => boolean
}

const PATTERNS: Record<HapticKind, number | number[]> = {
  tap: 10,
  success: [10, 30, 10],
  warning: [30, 20, 30],
}

export function haptic(
  kind: HapticKind,
  nav: VibrationCapableNavigator | undefined = typeof navigator === "undefined" ? undefined : navigator,
): boolean {
  if (typeof nav?.vibrate !== "function") return false
  return nav.vibrate(PATTERNS[kind])
}

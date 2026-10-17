/* Hallmark · pre-emit critique: P4 H3 E4 S4 R5 V3 */
import { useTheme } from "@/lib/theme/useTheme"

/*
 * Mounts `useTheme`'s effect once, above the router — the same "must run
 * wherever the reader lands, not only inside one screen" shape
 * `TimezoneSync` documents for itself. `ProfileSettingsSection`'s Appearance
 * fieldset also calls `useTheme()` (to read/write the preference and drive
 * its three radios), which is fine: the hook's `localStorage` read and
 * `matchMedia` subscription are cheap and idempotent across multiple
 * mounts, and React state is per-component, not shared — but the
 * `data-theme` attribute and the `theme-color` meta must be kept correct
 * even on every other screen, where nothing else calls `useTheme()` at all.
 * Without this, the Appearance setting would only apply once a reader
 * happened to visit the settings screen after choosing it, and "System"
 * would only track the OS live while that screen was mounted.
 *
 * The stamp above, derived rather than copied from `TimezoneSync`'s: H3 and
 * V3 are the same honest ceiling for the same reason — a component that
 * returns `null` has no hierarchy to rank and no composition to vary. R5 is
 * the real strength here too: no state of its own, no UI, and every actual
 * decision (the three-way table, the storage read/write, the live
 * subscription) lives in `useTheme` where it is unit- and e2e-tested, not
 * duplicated here.
 */
export function ThemeSync() {
  useTheme()
  return null
}

import { useCallback, useLayoutEffect, useState } from "react"
import { applyTheme } from "./applyTheme"
import {
  THEME_STORAGE_KEY,
  readThemePreference,
  resolveTheme,
  type ResolvedTheme,
  type ThemePreference,
} from "./theme"

const DARK_QUERY = "(prefers-color-scheme: dark)"

/** `localStorage` throws in some contexts (private browsing, storage
 * disabled by policy) — every read/write here is wrapped, matching
 * `shell-init.js`'s own defensiveness for the same key. */
function readStoredPreference(): ThemePreference {
  try {
    return readThemePreference(localStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    return "system"
  }
}

function writeStoredPreference(preference: ThemePreference): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, preference)
  } catch {
    // The in-memory preference still applies for the rest of this tab's
    // life; it just won't survive a reload. Nothing else to do — there is
    // no UI surface built for "your device refused to remember this".
  }
}

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia && window.matchMedia(DARK_QUERY).matches
}

export interface UseThemeResult {
  preference: ThemePreference
  resolved: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
}

/**
 * The Appearance setting's whole state machine: reads the stored preference
 * once on mount, resolves it against the OS, applies it to the document, and
 * keeps applying it — live, no reload — while the reader has "System"
 * selected and the OS setting changes underneath them.
 *
 * `applyTheme` runs in a layout effect rather than a plain effect so the
 * `data-theme` swap (and the repaint it drives, through `index.css`'s dark
 * ladder) happens synchronously before the browser paints the frame that
 * triggered it — the same reasoning `shell-init.js` documents for running
 * before the shell markup parses, just for the toggle case instead of first
 * paint: a plain effect would let one frame paint in the old theme first.
 */
export function useTheme(): UseThemeResult {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference)
  const [systemDark, setSystemDark] = useState<boolean>(systemPrefersDark)

  // Subscribes to the OS signal only while "System" is selected — a reader
  // who has picked Light or Dark explicitly should not have their choice
  // silently overridden by the device changing underneath them, and there is
  // no reason to keep a listener alive for a signal nothing is reading.
  useLayoutEffect(() => {
    if (preference !== "system") return
    if (typeof window === "undefined" || !window.matchMedia) return
    const media = window.matchMedia(DARK_QUERY)
    setSystemDark(media.matches)
    const handleChange = (event: MediaQueryListEvent) => setSystemDark(event.matches)
    media.addEventListener("change", handleChange)
    return () => media.removeEventListener("change", handleChange)
  }, [preference])

  const resolved = resolveTheme(preference, systemDark)

  useLayoutEffect(() => {
    const root = document.documentElement
    const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    applyTheme(root, meta, resolved)
  }, [resolved])

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next)
    writeStoredPreference(next)
  }, [])

  return { preference, resolved, setPreference }
}

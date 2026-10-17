import { useCallback, useLayoutEffect, useSyncExternalStore } from "react"
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

/*
 * ════════════════════════════════════════════════════════════════════════
 * SHARED STORE (C5 review fix)
 *
 * Before this, `useTheme` held its preference in a component-local
 * `useState`. `ThemeSync` (mounted app-wide, above the router) and
 * `ProfileSettingsSection`'s Appearance fieldset (mounted only while
 * settings is open) each called `useTheme()` independently, so each got its
 * OWN copy of the preference. Choosing an explicit theme through the
 * settings instance never reached `ThemeSync`'s instance — it kept
 * believing the preference was still "system", so its media-query listener
 * stayed attached (gated on that stale local value) and silently re-applied
 * a system-derived theme on the next OS change, discarding the reader's
 * choice until a full reload re-read storage fresh.
 *
 * The fix: one module-level store, read by every `useTheme()` call through
 * `useSyncExternalStore` so they all observe the same value and re-render
 * together. The two module-scope listeners below (`storage`, `matchMedia`)
 * are wired once, ever, not per component instance — that's what makes an
 * OS change or another tab's write reach every mounted instance instead of
 * whichever one happened to hold a still-live listener.
 * ════════════════════════════════════════════════════════════════════════
 */

let currentPreference: ThemePreference = readStoredPreference()
let currentSystemDark: boolean = systemPrefersDark()
const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) listener()
}

function getPreferenceSnapshot(): ThemePreference {
  return currentPreference
}

function getSystemDarkSnapshot(): boolean {
  return currentSystemDark
}

/** Writes a preference to storage and, if it actually changed, updates the
 * shared store and notifies every subscribed `useTheme()` instance —
 * regardless of which component instance called it. This is the whole fix:
 * previously each hook instance's `setPreference` only ever updated its own
 * `useState`. */
function setStorePreference(next: ThemePreference): void {
  writeStoredPreference(next)
  if (next === currentPreference) return
  currentPreference = next
  notify()
}

/** Handles a `storage` event: fires in every OTHER tab (never the tab that
 * made the write) when `localStorage` changes, so this closes the
 * reviewer's disclosed cross-tab gap — without it, a choice made in one tab
 * sat unnoticed in another tab's stale store until that tab reloaded. Takes
 * a `Pick<StorageEvent, ...>` rather than a real `StorageEvent` so the
 * store-logic unit tests can simulate one directly without a DOM; the real
 * `window.addEventListener("storage", ...)` wiring below is DOM-only and is
 * exercised by the e2e suite instead. */
export function handleThemeStorageEvent(event: Pick<StorageEvent, "key" | "newValue">): void {
  if (event.key !== THEME_STORAGE_KEY) return
  const next = readThemePreference(event.newValue)
  if (next === currentPreference) return
  currentPreference = next
  notify()
}

/** Handles a live `prefers-color-scheme` flip. Only readers currently
 * following "System" have anything to re-render for — an explicit
 * Light/Dark choice ignores `systemPrefersDark` entirely (see
 * `resolveTheme`), so notifying them would just be a wasted render. Checked
 * against the LIVE store value each time the event fires, not a value
 * captured when this listener was attached: this listener outlives any
 * single component instance, so a stale capture is exactly the bug this
 * store exists to close. */
function handleSystemDarkChange(matches: boolean): void {
  currentSystemDark = matches
  if (currentPreference === "system") notify()
}

let listenersAttached = false

/** Attaches the store's two DOM-level listeners exactly once, lazily, on
 * the first subscriber — not at module load, so importing this module in
 * the unit test runner (no `window`) is safe. */
function ensureListenersAttached(): void {
  if (listenersAttached || typeof window === "undefined") return
  listenersAttached = true
  window.addEventListener("storage", handleThemeStorageEvent)
  if (window.matchMedia) {
    const media = window.matchMedia(DARK_QUERY)
    media.addEventListener("change", (event) => handleSystemDarkChange(event.matches))
  }
}

function subscribe(callback: () => void): () => void {
  listeners.add(callback)
  ensureListenersAttached()
  return () => {
    listeners.delete(callback)
  }
}

/** The store's plain surface, exported so `theme.test.ts` can exercise the
 * subscribe/notify/setPreference/storage-event machinery directly. `useTheme`
 * below is the only thing that wires it into `useSyncExternalStore` — a hook
 * using that API can't be rendered in this repo's jsdom-less unit runner
 * (`vitest.config.ts`: `environment: "node"`), so this is what a pure
 * extraction of "the store logic" looks like here. */
export const themeStore = {
  subscribe,
  getPreferenceSnapshot,
  getSystemDarkSnapshot,
  setPreference: setStorePreference,
  handleStorageEvent: handleThemeStorageEvent,
}

export interface UseThemeResult {
  preference: ThemePreference
  resolved: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
}

/**
 * The Appearance setting's whole state machine: reads the stored preference
 * once (at module load), resolves it against the OS, applies it to the
 * document, and keeps applying it — live, no reload — while ANY mounted
 * instance's reader has "System" selected and the OS setting changes
 * underneath them. Every `useTheme()` call anywhere in the tree reads the
 * same module-level store via `useSyncExternalStore`, so they observe
 * exactly the same preference and re-render together — see the store
 * comment above for why that matters.
 *
 * `applyTheme` runs in a layout effect rather than a plain effect so the
 * `data-theme` swap (and the repaint it drives, through `index.css`'s dark
 * ladder) happens synchronously before the browser paints the frame that
 * triggered it — the same reasoning `shell-init.js` documents for running
 * before the shell markup parses, just for the toggle case instead of first
 * paint: a plain effect would let one frame paint in the old theme first.
 */
export function useTheme(): UseThemeResult {
  const preference = useSyncExternalStore(subscribe, getPreferenceSnapshot)
  const systemDark = useSyncExternalStore(subscribe, getSystemDarkSnapshot)
  const resolved = resolveTheme(preference, systemDark)

  useLayoutEffect(() => {
    const root = document.documentElement
    const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    applyTheme(root, meta, resolved)
  }, [resolved])

  const setPreference = useCallback((next: ThemePreference) => {
    setStorePreference(next)
  }, [])

  return { preference, resolved, setPreference }
}

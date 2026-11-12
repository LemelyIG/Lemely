import { useSyncExternalStore } from "react"

/*
 * PR 2 part C · connectivity primitive.
 *
 * `navigator.onLine` is the browser's own "do I currently have a link-layer
 * connection" signal — it is not "can I reach the backend" (a captive portal
 * or a dead upstream still reads `true`), but it is the only cue this app
 * gets for free, and it is exactly the cue OFFLINE_BANNER and the "back
 * online" recovery in `recovery-effects.tsx` are built around: both react to
 * the browser's own online/offline events, not to a query's own success or
 * failure.
 *
 * `isOnline` and `subscribeOnline` are split out as plain functions, rather
 * than folded straight into the hook, so `useOnlineStatus`'s only job is
 * wiring them into `useSyncExternalStore` — the two pieces that actually
 * touch `window`/`navigator` stay individually reachable (and, if a future
 * caller ever needs the raw value or the raw subscription outside a
 * component, already exported).
 */

/** Read the browser's current connectivity flag. `typeof navigator ===
 * "undefined"` covers the same non-browser callers `clientErrors.ts` guards
 * for (SSR, a test runner with no DOM) — reading as "online" there is the
 * safe default, since nothing in this app runs offline-only logic outside a
 * real browser tab. */
export function isOnline(): boolean {
  return typeof navigator === "undefined" ? true : navigator.onLine
}

/** Subscribe to the browser's `online`/`offline` events, calling `listener`
 * with the new state on each. Returns an unsubscribe function. */
export function subscribeOnline(listener: (online: boolean) => void): () => void {
  const handleOnline = () => listener(true)
  const handleOffline = () => listener(false)
  window.addEventListener("online", handleOnline)
  window.addEventListener("offline", handleOffline)
  return () => {
    window.removeEventListener("online", handleOnline)
    window.removeEventListener("offline", handleOffline)
  }
}

/**
 * The live `navigator.onLine` value, re-rendering the calling component on
 * every `online`/`offline` transition.
 *
 * `useSyncExternalStore`'s third argument is the server snapshot, used for
 * both actual SSR and React's hydration-mismatch check — this app never
 * server-renders, but the argument is still required, and `true` (never
 * "offline" before a browser has had a chance to say otherwise) is the same
 * safe default `isOnline`'s own `typeof navigator` guard falls back to.
 */
export function useOnlineStatus(): boolean {
  return useSyncExternalStore(subscribeOnline, isOnline, () => true)
}

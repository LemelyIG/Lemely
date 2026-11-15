import { isStandaloneDisplay } from "@/lib/pwa/useInstallPrompt"
import { PHONE_MEDIA, isNativeFrame } from "@/lib/useNativeFrame"
import { readPlatform } from "@/lib/platform"
import type { NavigateMiddleware } from "@/lib/nav/navigateMiddleware"
import { getSession, subscribeToSession } from "@/lib/auth/storage"
import { captureColumn, createSnapshotStore, navigateSnapshotAction, watchSessionForSnapshots, type PageSnapshot } from "@/lib/nav/pageSnapshot"

/** The app's one snapshot store, keyed by `history.state.idx`. */
export const pageSnapshots = createSnapshotStore<PageSnapshot>()

const COLUMN = "[data-shell-column]"

/** Snapshots exist only where the swipe-back underlay can show: the native frame, installed. */
export function snapshotsEnabled(): boolean {
  if (typeof window === "undefined") return false
  if (!isNativeFrame(readPlatform(), window.matchMedia(PHONE_MEDIA).matches)) return false
  return isStandaloneDisplay(
    window.matchMedia("(display-mode: standalone)"),
    (window.navigator as Navigator & { standalone?: boolean }).standalone,
  )
}

/** The User Timing name every capture is recorded under (`performance.getEntriesByName`). */
export const CAPTURE_MEASURE = "lemely:snapshot-capture"
/** Measures kept in the performance buffer before the oldest are cleared. */
const MEASURE_KEEP = 100

/**
 * History indices whose page was over the node cap. The walk stops at the cap, but an oversized
 * page would still pay up to `SNAPSHOT_NODE_CAP` elements of work on every push away from it, so
 * the verdict is remembered. Forgotten when that index's page can change (a replace, a push that
 * overwrites forward history, a session change).
 */
const oversized = new Set<number>()

export function isRememberedOversized(idx: number): boolean {
  return oversized.has(idx)
}

/** Drop the copies and the oversized verdicts at `idx` and beyond (a push overwrites the forward history). */
export function dropSnapshotsFrom(idx: number): void {
  pageSnapshots.dropFrom(idx)
  for (const key of [...oversized]) if (key >= idx) oversized.delete(key)
}

function recordMeasure(start: number, idx: number, outcome: "kept" | "oversized"): void {
  if (typeof performance === "undefined" || typeof performance.measure !== "function") return
  try {
    if (performance.getEntriesByName(CAPTURE_MEASURE).length >= MEASURE_KEEP) performance.clearMeasures(CAPTURE_MEASURE)
    performance.measure(CAPTURE_MEASURE, { start, end: performance.now(), detail: { idx, outcome } })
  } catch {
    // Measuring is diagnostics only.
  }
}

/** Clone the page currently shown and file it under its history index. */
export function captureCurrentPage(): void {
  const idx = window.history.state?.idx
  if (typeof idx !== "number" || !snapshotsEnabled()) return
  if (oversized.has(idx)) return
  const column = document.querySelector<HTMLElement>(COLUMN)
  if (!column) return
  const start = performance.now()
  const snap = captureColumn(column, window.scrollY)
  if (snap) pageSnapshots.set(idx, snap)
  else {
    pageSnapshots.delete(idx)
    oversized.add(idx)
  }
  recordMeasure(start, idx, snap ? "kept" : "oversized")
}

/** Drop every snapshot when the session ends or the user changes. Call once at app start. */
export function installSnapshotSessionGuard(): () => void {
  const store = {
    clear() {
      pageSnapshots.clear()
      oversized.clear()
    },
  }
  return watchSessionForSnapshots(subscribeToSession, store, getSession()?.userId ?? null)
}

/**
 * Navigate middleware (see `navigateMiddleware.ts`). Every push (a Link, a button calling
 * `navigate()`) passes through it while the DOM and `history.state.idx` still belong to the page
 * being left, so the page is cloned exactly then, with its real scroll. A replace swaps the page
 * at the same index, so that index's old copy is dropped instead. A numeric delta is a back or
 * forward: nothing to do.
 */
export const snapshotCaptureMiddleware: NavigateMiddleware = (to, options, next) => {
  // The snapshot is a nicety under a gesture. Whatever goes wrong while copying the page, the
  // navigation must still run, so `next` is outside the try.
  try {
    const action = navigateSnapshotAction(to, options)
    if (action === "capture") captureCurrentPage()
    else if (action === "drop") {
      const idx = window.history.state?.idx
      if (typeof idx === "number") {
        pageSnapshots.delete(idx)
        oversized.delete(idx)
      }
    }
  } catch (error) {
    if (import.meta.env.DEV) console.error("snapshot capture failed; navigating anyway", error)
  }
  return next(to, options)
}

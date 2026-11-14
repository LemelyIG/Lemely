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

/** Clone the page currently shown and file it under its history index. */
export function captureCurrentPage(): void {
  const idx = window.history.state?.idx
  if (typeof idx !== "number" || !snapshotsEnabled()) return
  const column = document.querySelector<HTMLElement>(COLUMN)
  if (!column) return
  const snap = captureColumn(column, window.scrollY)
  if (snap) pageSnapshots.set(idx, snap)
  else pageSnapshots.delete(idx)
}

/** Drop every snapshot when the session ends or the user changes. Call once at app start. */
export function installSnapshotSessionGuard(): () => void {
  return watchSessionForSnapshots(subscribeToSession, pageSnapshots, getSession()?.userId ?? null)
}

/**
 * Navigate middleware (see `navigateMiddleware.ts`). Every push (a Link, a button calling
 * `navigate()`) passes through it while the DOM and `history.state.idx` still belong to the page
 * being left, so the page is cloned exactly then, with its real scroll. A replace swaps the page
 * at the same index, so that index's old copy is dropped instead. A numeric delta is a back or
 * forward: nothing to do.
 */
export const snapshotCaptureMiddleware: NavigateMiddleware = (to, options, next) => {
  const action = navigateSnapshotAction(to, options)
  if (action === "capture") captureCurrentPage()
  else if (action === "drop") {
    const idx = window.history.state?.idx
    if (typeof idx === "number") pageSnapshots.delete(idx)
  }
  return next(to, options)
}

import { isStandaloneDisplay } from "@/lib/pwa/useInstallPrompt"
import { PHONE_MEDIA, isNativeFrame } from "@/lib/useNativeFrame"
import { readPlatform } from "@/lib/platform"
import { captureColumn, createSnapshotStore, type PageSnapshot } from "@/lib/nav/pageSnapshot"

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

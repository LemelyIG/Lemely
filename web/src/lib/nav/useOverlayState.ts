import { useLocation } from "react-router-dom"
import { backgroundState, historyIndexOf, type BackgroundState } from "./backgroundLocation"

/**
 * The `state` a link into an overlay route (Settings) should carry: the page
 * the reader is on now (and its history index), so the dialog opens over it
 * and closing walks back to it.
 * Pass it as `<Link to={...} state={useOverlayState()}>`.
 */
export function useOverlayState(): BackgroundState {
  const { pathname, search, hash } = useLocation()
  const historyState = typeof window === "undefined" ? null : window.history.state
  const idx = historyIndexOf(historyState)
  // A link inside an open dialog replaces the dialog's own entry (`dialogExit`),
  // so the page underneath sits one entry below the current one.
  const inDialog = (historyState as { usr?: { lemelyDialog?: boolean } } | null)?.usr?.lemelyDialog === true
  return backgroundState({ pathname, search, hash }, idx !== null && inDialog ? Math.max(0, idx - 1) : idx)
}

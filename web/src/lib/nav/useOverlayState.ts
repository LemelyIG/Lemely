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
  const idx = typeof window === "undefined" ? null : historyIndexOf(window.history.state)
  return backgroundState({ pathname, search, hash }, idx)
}

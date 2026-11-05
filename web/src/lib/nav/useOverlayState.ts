import { useLocation } from "react-router-dom"
import { backgroundState, type BackgroundState } from "./backgroundLocation"

/**
 * The `state` a link into an overlay route (Settings) should carry: the page
 * the reader is on now, so the dialog opens over it and closing returns to it.
 * Pass it as `<Link to={...} state={useOverlayState()}>`.
 */
export function useOverlayState(): BackgroundState {
  const { pathname, search, hash } = useLocation()
  return backgroundState({ pathname, search, hash })
}

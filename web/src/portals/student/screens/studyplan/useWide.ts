import { useSyncExternalStore } from "react"

/* The shell shows its rail at 1280px and up, and the session sheet becomes a side panel there too. */
const QUERY = "(min-width: 1280px)"

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(QUERY)
  media.addEventListener("change", onChange)
  return () => media.removeEventListener("change", onChange)
}

/** True at the desktop breakpoint. False on the server, where there is nothing to measure. */
export function useWide(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches, () => false)
}

import { useSyncExternalStore } from "react"

/** Desktop breakpoint (Tailwind `lg`). Picks Binny's single slot; never used to CSS-hide a copy. */
const QUERY = "(min-width: 1024px)"

function subscribe(onChange: () => void): () => void {
  const mq = window.matchMedia(QUERY)
  mq.addEventListener("change", onChange)
  return () => mq.removeEventListener("change", onChange)
}

export function useWide(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => false,
  )
}

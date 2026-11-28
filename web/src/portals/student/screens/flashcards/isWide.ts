import { useSyncExternalStore } from "react"

export const WIDE_QUERY = "(min-width: 1024px)"
export const isWide = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(WIDE_QUERY).matches

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {}
  const mq = window.matchMedia(WIDE_QUERY)
  mq.addEventListener("change", onChange)
  return () => mq.removeEventListener("change", onChange)
}

/** True at lg, where the shelf has a side panel and a row can be selected. False on the server. */
export function useIsWide(): boolean {
  return useSyncExternalStore(subscribe, isWide, () => false)
}

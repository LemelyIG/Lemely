export const WIDE_QUERY = "(min-width: 1024px)"
export const isWide = () => typeof window !== "undefined" && window.matchMedia(WIDE_QUERY).matches

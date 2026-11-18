/**
 * Focus return for sheets opened without a Radix `Trigger`. Radix hands focus back to the Trigger on
 * close; with none it drops to `body`. The sheet records the element that had focus when it opened
 * and puts focus back there on close.
 */

/** The slice of an element the decision reads, so the helper is testable without a DOM. */
export interface FocusOpener {
  isConnected: boolean
  getAttribute(name: string): string | null
}

/** The opener to focus again on close, or null when Radix's own return (or the caller's) should run. */
export function focusReturnTarget<T extends FocusOpener>(
  opener: T | null | undefined,
  contentId?: string | null,
  body?: unknown,
): T | null {
  if (!opener || !opener.isConnected) return null
  if (body !== undefined && opener === body) return null
  // A Radix Trigger points at its content; leave that to the Radix default.
  if (contentId && opener.getAttribute("aria-controls") === contentId) return null
  return opener
}

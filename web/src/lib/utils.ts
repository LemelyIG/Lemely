import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/** Merge conditional class names, de-duplicating Tailwind utilities. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Format an ISO-8601 timestamp as a short relative-time label ("3d ago",
 * "just now"). Used wherever a screen renders a "last activity"/"last active"
 * instant (teacher class cards/table, recent-activity feed) — a glance-level
 * read, not a precise duration.
 */
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  const minutes = Math.floor((Date.now() - then) / 60_000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.floor(months / 12)}y ago`
}

/**
 * First letter of each word in a display name, for an avatar's initials
 * ("Yassin Diab" -> "YD"). Was duplicated identically in
 * `portals/teacher/screens/Overview.tsx` and `Review.tsx` (both had their own
 * private copy despite STATE.md/several chunk notes claiming it already
 * lived here) — moved here in P3.7 chunk c so a third near-identical copy
 * wasn't added for the T-03/T-04 screens; the two existing call sites now
 * import this instead of defining it locally.
 */
export function initialsOf(name: string): string {
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
}

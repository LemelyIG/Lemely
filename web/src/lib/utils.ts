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

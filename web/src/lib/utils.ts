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

/** RFC 4180 quoting: a cell containing a quote, comma or newline is wrapped
 * in quotes with its own quotes doubled. */
function escapeCsvCell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/**
 * Serialize `rows` as CSV and hand it to the browser as a download.
 *
 * Extracted from `ClassAnalytics.tsx`'s private heatmap exporter in P3.8
 * chunk d, when T-10 needed the same escape-and-download mechanics — the
 * `initialsOf` lesson from P3.7 chunk c (a helper copied into a second screen
 * is a helper that will be copied into a third, and the copies drift). Each
 * screen still builds its own `rows`; only the escaping and the Blob/anchor
 * dance are shared.
 *
 * `filename` is slugified, so callers pass a human label ("Y11 Physics —
 * quiz 3") rather than pre-sanitising it themselves.
 */
export function downloadCsv(filename: string, rows: string[][]): void {
  const csv = rows.map((row) => row.map(escapeCsvCell).join(",")).join("\n")
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `${filename.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

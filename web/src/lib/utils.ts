import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

/**
 * Every `text-`-prefixed font-size class we define ourselves, declared to
 * tailwind-merge as font-sizes.
 *
 * Without this they fall into twMerge's default `text-color` class group —
 * the trap `index.css` documents above `.btn-text*`, which was only ever
 * worked around for the button rungs by renaming them out of the `text-`
 * namespace. The composite type-scale classes were left in it, and the bug
 * was live: `twMerge("text-display-md text-t1")` returned `"text-t1"`,
 * silently dropping the font-size/family/line-height, and
 * `twMerge("text-metadata mt-1", <a color>)` dropped the type class the same
 * way. Five shared C-* components hit exactly that shape (trend-sparkline x2,
 * boundary-bar, confidence-indicator, paper-identity), so the defect shipped
 * on every screen composing them — invisibly, since a dropped type class
 * degrades to inherited type rather than to a visible error.
 *
 * `text-2xs`/`text-3xs` were always safe by accident: twMerge's default
 * font-size validator accepts t-shirt-shaped suffixes. Registering them here
 * anyway makes that intentional rather than a naming coincidence, and lets
 * the density rungs below use honest names instead of contorting to fit the
 * t-shirt pattern.
 *
 * P3.10 chunk c. Pinned by `cn`'s own tests — do not remove a name from this
 * list without removing the class from `index.css` too.
 */
const CUSTOM_FONT_SIZE_CLASSES = [
  // ── Study Notebook type scale (DESIGN.md §4.2) ──
  "display-hero",
  "display-xl",
  "display-lg",
  "display-md",
  "display-sm",
  "body-lg",
  "body-md",
  "body-sm",
  "label",
  "eyebrow",
  "data-lg",
  "data-md",
  "data-sm",
  "hand",
  // ── Build-era names, still live until Phase 4 migrates the last call site ──
  "display-xs",
  "label-sm",
  "metadata",
  "dense-lg",
  "dense",
  "dense-sm",
  "md",
  "2xs",
  "3xs",
] as const

const twMerge = extendTailwindMerge({
  extend: { classGroups: { "font-size": [{ text: [...CUSTOM_FONT_SIZE_CLASSES] }] } },
})

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

/**
 * Time-of-day greeting for a 0-23 hour, in the reader's own local time.
 *
 * The student Overview said "Good afternoon" unconditionally, at every hour of
 * the day, which made the first line of the first screen the one sentence on
 * the page that was reliably false for most of its readers — students revise
 * at night.
 *
 * A pure function taking the hour rather than reading the clock itself, so it
 * is testable at every boundary without faking timers. Evening runs from 18:00
 * round to 04:59 deliberately: greeting someone with "good morning" at two in
 * the morning is the same error in the other direction, and a student still
 * working at that hour has not started their morning yet.
 */
export function greetingFor(hour: number): string {
  if (hour >= 5 && hour < 12) return "Good morning"
  if (hour >= 12 && hour < 18) return "Good afternoon"
  return "Good evening"
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

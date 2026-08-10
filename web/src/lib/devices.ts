import type { Device } from "./deviceTypes"

/*
 * Rendering helpers shared by G-10 and G-11 so the same device reads the same
 * way in the screen that asks and the screen that manages.
 */

/**
 * A short, human description of a device from its `User-Agent`.
 *
 * Deliberately coarse. A user-agent string is a hint, not an identity: it is
 * spoofable, browsers lie about each other in it by design, and no amount of
 * parsing turns it into "Yassin's iPhone". So this returns at most a browser
 * and a platform, and falls back to "Unknown device" rather than guessing —
 * the same reason there is no location field (D5.12 §5). The raw string stays
 * available in the DOM `title` so a suspicious user can see what we actually
 * hold instead of only our summary of it.
 */
export function describeUserAgent(userAgent: string | null): string {
  if (!userAgent) return "Unknown device"
  const browser = matchFirst(userAgent, [
    [/edg\//i, "Edge"],
    [/opr\/|opera/i, "Opera"],
    [/firefox\//i, "Firefox"],
    [/chrome\//i, "Chrome"],
    [/safari\//i, "Safari"],
  ])
  const platform = matchFirst(userAgent, [
    [/iphone/i, "iPhone"],
    [/ipad/i, "iPad"],
    [/android/i, "Android"],
    [/windows/i, "Windows"],
    [/mac os x|macintosh/i, "Mac"],
    [/linux/i, "Linux"],
  ])
  if (browser && platform) return `${browser} on ${platform}`
  return browser ?? platform ?? "Unknown device"
}

function matchFirst(value: string, table: [RegExp, string][]): string | null {
  for (const [pattern, name] of table) {
    if (pattern.test(value)) return name
  }
  return null
}

/** The name to show for a device: its own label if it has one, else its user agent. */
export function deviceTitle(device: Device): string {
  return device.label ?? describeUserAgent(device.userAgent)
}

/**
 * "Active 3 hours ago" — coarse on purpose.
 *
 * Rounding down to the largest whole unit avoids implying a precision the
 * `last_seen_at` stamp does not carry (it moves only when a request is made,
 * so a device idle in a background tab is "active" whenever its last poll was).
 */
export function lastActiveLabel(iso: string, now: Date = new Date()): string {
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return "Last active: unknown"
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60_000)
  if (minutes < 1) return "Active just now"
  if (minutes < 60) return `Active ${plural(minutes, "minute")} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `Active ${plural(hours, "hour")} ago`
  return `Active ${plural(Math.floor(hours / 24), "day")} ago`
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"}`
}

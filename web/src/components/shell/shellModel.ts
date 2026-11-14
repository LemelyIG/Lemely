/*
 * Pure shell logic, unit-tested in tests/unit/shellModel.test.ts (the unit
 * runner has no DOM, so anything worth pinning lives here, not in a component).
 */

/** The bell's accessible name. `unread` is `unreadBadgeLabel(counts)`. */
export function notificationsTriggerLabel(unread: string | null): string {
  return unread ? `Notifications, ${unread} unread` : "Notifications"
}

/** A run of a notification title, flagged when design A sets it in the mono
 * face (`<span class="a-mono">`): a paper code ("0580/42") or a day and month
 * ("12 Nov"). The paper code comes first in the alternation, it is the more
 * restrictive pattern. */
export interface TitleRun {
  text: string
  mono: boolean
}

const MONO_RUN = /(\d{4}\/\d{2}|(?:\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) )?\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b)/

export function titleRuns(title: string): TitleRun[] {
  return title
    .split(MONO_RUN)
    .map((text, i) => ({ text, mono: i % 2 === 1 }))
    .filter((run) => run.text !== "")
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

/** The bell panel's time column, as design A writes it: the clock time today
 * ("9:12"), the weekday within the last six days ("Wed"), day and month
 * before that ("27 Oct"). The exact instant stays in `<time dateTime>`. */
export function panelTimeLabel(iso: string, now: Date = new Date()): string {
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return ""
  const sameDay =
    t.getFullYear() === now.getFullYear() && t.getMonth() === now.getMonth() && t.getDate() === now.getDate()
  if (sameDay) return `${t.getHours()}:${String(t.getMinutes()).padStart(2, "0")}`
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const days = Math.ceil((startOfToday - t.getTime()) / 86_400_000)
  if (days >= 0 && days < 7) return WEEKDAYS[t.getDay()]
  return `${t.getDate()} ${MONTHS[t.getMonth()]}`
}

const STEP: Record<string, 1 | -1> = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }

/** Arrow keys move between settings tabs (up/down on the rail, left/right on
 * the phone strip), wrapping; Home and End jump to the ends. */
export function nextSettingsTabIndex(
  current: number,
  key: string,
  count: number,
  mods: { altKey?: boolean; ctrlKey?: boolean; metaKey?: boolean } = {},
): number | null {
  // Alt+Arrow is browser history, Ctrl/Cmd+Arrow belongs to the OS and
  // assistive tech: only a bare key moves between tabs.
  if (mods.altKey || mods.ctrlKey || mods.metaKey) return null
  if (current < 0 || count <= 0) return null
  if (key in STEP) return (current + STEP[key] + count) % count
  if (key === "Home") return 0
  if (key === "End") return count - 1
  return null
}

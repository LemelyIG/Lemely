const DAY_MS = 86_400_000
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})(?:$|[T\s])/

/**
 * Whole calendar days from `now`'s local date to the exam's calendar date; NaN when either is unreadable.
 *
 * Both sides are reduced to a bare Y-M-D and compared as UTC midnights, so the time of day, a 23h or 25h
 * DST day and the viewer's zone cannot move the answer by a day. The exam date is a calendar date, not an
 * instant: a stamp such as "2027-05-14T09:00:00Z" counts as 14 May wherever the viewer is.
 */
export function daysUntil(examDate: string, now: Date = new Date()): number {
  const match = DATE_ONLY.exec(examDate.trim())
  if (!match) return Number.NaN
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const exam = new Date(Date.UTC(y, m - 1, d))
  // Date.UTC rolls 30 Feb into March; reject anything that did not round-trip.
  if (exam.getUTCFullYear() !== y || exam.getUTCMonth() !== m - 1 || exam.getUTCDate() !== d) return Number.NaN
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.round((exam.getTime() - today) / DAY_MS)
}

/** Neutral until 30 days before the exam, then Tide (spec: exam countdown decision). Neutral when unreadable. */
export function countdownTone(examDate: string, now?: Date): "neutral" | "near" {
  const days = daysUntil(examDate, now)
  return days >= 0 && days <= 30 ? "near" : "neutral"
}

/** "180 days to exams", "1 day to Physics", "Exams today", "188 days" (subject null). Null after the exam or when unreadable. */
export function countdownLabel(days: number, subject: string | null = "exams"): string | null {
  if (!Number.isFinite(days) || days < 0) return null
  if (days === 0) return subject === null || subject === "exams" ? "Exams today" : `${subject} today`
  const span = `${days} ${days === 1 ? "day" : "days"}`
  return subject === null ? span : `${span} to ${subject}`
}

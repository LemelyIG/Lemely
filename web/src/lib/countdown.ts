/*
 * Exam countdown arithmetic. Moved out of `Announcements.tsx` (C3b) so the
 * study-plan week header can use the same two functions — S-28's countdown
 * and S-24's countdown are the same fact ("days until this exam") and must
 * not drift into two slightly different implementations.
 */

/**
 * Whole days from today to `examDate`, both read as civil dates.
 *
 * Deliberately **not** hour-based: a student opening this at 23:00 and again
 * at 01:00 should not see "3 days" become "2 days" over one night's sleep
 * when the exam is the same calendar distance away. `startsAtLocal` is often
 * absent anyway (the timetable does not always print one), so an
 * hour-precise countdown would be precision we do not have.
 */
export function daysUntil(examDate: string, today: Date): number {
  const exam = new Date(`${examDate}T00:00:00`)
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  return Math.round((exam.getTime() - start.getTime()) / 86_400_000)
}

export function formatCountdown(days: number): string {
  if (days === 0) return "Today"
  if (days === 1) return "Tomorrow"
  return `${days} days`
}

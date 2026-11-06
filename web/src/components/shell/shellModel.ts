/** Day-granularity age, identical to the student inbox's `formatAge`
 * (`portals/student/screens/Notifications.tsx`). Replaced by `panelTimeLabel`
 * in Task 3. */
export function formatAge(iso: string, now: Date = new Date()): string {
  const created = new Date(iso)
  if (Number.isNaN(created.getTime())) return ""
  const days = Math.floor((now.getTime() - created.getTime()) / 86_400_000)
  if (days <= 0) return "Today"
  if (days === 1) return "Yesterday"
  if (days < 7) return `${days} days ago`
  const weeks = Math.floor(days / 7)
  if (weeks === 1) return "1 week ago"
  if (weeks < 5) return `${weeks} weeks ago`
  return created.toLocaleDateString(undefined, { day: "numeric", month: "short" })
}

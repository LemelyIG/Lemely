/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Navigate } from "react-router-dom"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { useOverview } from "@/lib/hooks/useStudentApi"

/**
 * Interim Practice and Plan tab root (F1). There is no subject-free practice or plan screen yet, so each
 * opens its entry for the first subject, or Home when the student has none. L4 and L9 replace these routes'
 * element with the real hubs. Redirect only: nothing here to show an error for.
 */
export function SubjectEntry({ section }: { section: "practice" | "plan" }) {
  const overview = useOverview()
  if (overview.isPending) return <RouteSkeleton />
  const first = overview.data?.subjects[0]?.code
  return <Navigate to={first ? `/student/${section}/${encodeURIComponent(first)}` : "/student"} replace />
}

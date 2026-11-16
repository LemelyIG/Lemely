/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Navigate } from "react-router-dom"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { useOverview } from "@/lib/hooks/useStudentApi"

/**
 * Interim Plan tab root (F1). There is no subject-free plan screen yet, so this
 * opens the current plan entry for the first subject, or Home when the student
 * has none. The redesign lane replaces this route's element with the real screen.
 */
export function PlanEntry() {
  const overview = useOverview()
  if (overview.isPending) return <RouteSkeleton />
  const first = overview.data?.subjects[0]?.code
  return <Navigate to={first ? `/student/plan/${encodeURIComponent(first)}` : "/student"} replace />
}

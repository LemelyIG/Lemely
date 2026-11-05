/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useNavigate } from "react-router-dom"
import { useTeacherClasses, useTeacherOverview } from "@/lib/hooks/useTeacherApi"
import { teacherLoadFailureMessage } from "@/lib/teacherOutcome"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { deriveSetup, teacherHomeView } from "./setup"
import { TeacherSetup } from "./TeacherSetup"
import { Overview as OverviewScreen } from "../screens/Overview"

export function TeacherHome() {
  const navigate = useNavigate()
  const classes = useTeacherClasses()
  const overview = useTeacherOverview()
  const view = teacherHomeView(classes.status, classes.data?.classes.length ?? 0, overview.status, overview.data)
  const toGrading = (files: File[]) => navigate("/teacher/grading", { state: { files } })
  if (view === "loading") return <RouteSkeleton />
  if (view === "error") {
    return (
      <div role="alert" className="rounded-card bg-error-container p-6 text-on-error-container">
        <p className="font-bold">We couldn't load your overview.</p>
        <p className="mt-1 text-body-sm">{teacherLoadFailureMessage(classes.error ?? overview.error)}</p>
        <button type="button" disabled={classes.isFetching || overview.isFetching} className="mt-3 font-bold underline disabled:opacity-50 disabled:no-underline" onClick={() => { void classes.refetch(); void overview.refetch() }}>Try again</button>
      </div>
    )
  }
  if (view === "setup") {
    return <TeacherSetup progress={deriveSetup(classes.data!.classes.length, overview.data!)} firstClass={classes.data!.classes[0] ?? null} onFiles={toGrading} />
  }
  return <OverviewScreen overview={overview.data!} classes={classes.data!.classes} onFiles={toGrading} />
}

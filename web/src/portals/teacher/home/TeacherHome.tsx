import { useNavigate } from "react-router-dom"
import { useTeacherClasses, useTeacherOverview } from "@/lib/hooks/useTeacherApi"
import type { Overview } from "@/lib/teacherTypes"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { deriveSetup } from "./setup"
import { TeacherSetup } from "./TeacherSetup"
import { Overview as OverviewScreen } from "../screens/Overview"

type Status = "pending" | "error" | "success"
export type HomeView = "loading" | "error" | "setup" | "overview"

export function teacherHomeView(
  classesStatus: Status, classCount: number, overviewStatus: Status,
  overview: Pick<Overview, "paperCount" | "pendingReviewCount"> | undefined,
): HomeView {
  if (classesStatus === "error" || overviewStatus === "error") return "error"
  if (classesStatus === "pending" || overviewStatus === "pending" || !overview) return "loading"
  const s = deriveSetup(classCount, overview)
  return s.created && s.uploaded ? "overview" : "setup"
}

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
        <button type="button" className="mt-3 font-bold underline" onClick={() => { void classes.refetch(); void overview.refetch() }}>Try again</button>
      </div>
    )
  }
  if (view === "setup") {
    return <TeacherSetup progress={deriveSetup(classes.data!.classes.length, overview.data!)} firstClass={classes.data!.classes[0] ?? null} onFiles={toGrading} />
  }
  return <OverviewScreen overview={overview.data!} classes={classes.data!.classes} onFiles={toGrading} />
}

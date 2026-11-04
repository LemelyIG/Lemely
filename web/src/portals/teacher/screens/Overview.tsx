import type { ClassSummary, Overview as OverviewDTO } from "@/lib/teacherTypes"
import { ReviewQueueTile } from "../home/ReviewQueueTile"
import { MarkClassSet } from "../home/MarkClassSet"
import { ClassStrip } from "../home/ClassStrip"
import { AtRiskTable } from "../home/AtRiskTable"

/** Teacher home (T-01), v5 Abyss. Data comes from TeacherHome; this file only lays it out. */
export function Overview({ overview, classes, onFiles }: { overview: OverviewDTO; classes: ClassSummary[]; onFiles: (files: File[]) => void }) {
  const last = overview.recentActivity[0]
  const lastUpload = last ? `${last.subjectCode} · ${new Date(last.recordedAt).toLocaleDateString(undefined, { weekday: "short" })}` : null
  return (
    <div className="grid gap-8">
      <div className="grid gap-6 lg:grid-cols-2">
        <ReviewQueueTile overview={overview} />
        <MarkClassSet lastUpload={lastUpload} onFiles={onFiles} />
      </div>
      <ClassStrip classes={classes} />
      <AtRiskTable students={overview.atRisk} />
    </div>
  )
}

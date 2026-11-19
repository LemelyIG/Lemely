/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { relativeTime } from "@/lib/utils"
import type { ClassSummary, Overview as OverviewDTO } from "@/lib/teacherTypes"
import { ReviewQueueTile } from "../home/ReviewQueueTile"
import { MarkClassSet } from "../home/MarkClassSet"
import { ClassStrip } from "../home/ClassStrip"
import { AtRiskTable } from "../home/AtRiskTable"
import { NextUp } from "../home/NextUp"
import { growthModel, hasTrends } from "../home/growth"

/** Teacher home (T-01), v5 Abyss. Data comes from TeacherHome; this file only lays it out. */
export function Overview({ overview, classes, onFiles }: { overview: OverviewDTO; classes: ClassSummary[]; onFiles: (files: File[]) => void }) {
  // A quiz attempt is not an upload, so "Last:" skips those rows.
  const last = overview.recentActivity.find((a) => a.origin !== "quiz")
  const lastUpload = last ? `${last.subjectCode} · ${relativeTime(last.recordedAt)}` : null
  const growth = growthModel(classes, overview)
  return (
    <div className="grid grid-cols-1 gap-8">
      <h1 className="sr-only">Overview</h1>
      {/* grid-cols-1 is minmax(0, 1fr): an implicit `auto` column grows to the
          class strip's min-content (three 280px cards), clipping every tile at 375. */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] xl:grid-cols-2">
        <ReviewQueueTile overview={overview} />
        <MarkClassSet lastUpload={lastUpload} onFiles={onFiles} />
      </div>
      <NextUp growth={growth} />
      <ClassStrip classes={classes} />
      <AtRiskTable students={overview.atRisk} trendsReady={hasTrends(classes)} />
    </div>
  )
}

import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { DownloadSimple } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { ErrorState, EmptyState } from "@/components/ui/state-views"
import { TrendSparkline } from "@/components/ui/trend-sparkline"
import { WeaknessChip, type WeaknessSeverity } from "@/components/ui/weakness-chip"
import { gradeBand } from "@/components/ui/grade-badge"
import { cn } from "@/lib/utils"
import { useClassAnalytics } from "@/lib/hooks/useTeacherApi"
import type { HeatmapCell, TopicWeakness } from "@/lib/teacherTypes"
import { useClassDetailContext } from "./ClassDetail"

/*
 * Class detail — analytics (T-04). Reads the class header via
 * `useClassDetailContext()` (for the roster's student id -> display name
 * map — `ClassAnalyticsDTO`'s heatmap/weakness rows carry only ids) and runs
 * its own `GET /classes/{classId}/analytics` (`useClassAnalytics()`).
 *
 * Five panels, one DTO field each: `topicWeaknesses` (ranking) + `heatmap`
 * (cells) together drive the centrepiece topic x student matrix;
 * `gradeDistribution` the grade bars; `trend` the cohort sparkline;
 * `paperComparison` the per-paper table; `engagement` the activity stats.
 *
 * **Heatmap no-data vs. 0% (the one rule this screen cannot get wrong):**
 * `HeatmapCellDTO.accuracy` is `null` when a student has no persisted
 * weak-area entry for a topic — the core module's docstring is explicit
 * that this is NOT the same as scoring 0% (a student who never attempted a
 * topic looks identical, in what's persisted, to one who scored 100% on
 * every question on it — see `lemely/core/class_analytics.py`'s module
 * docstring). A `null` cell renders as a distinct hatched/neutral cell with
 * an en-dash glyph and its own `aria-label` ("No data"); a real 0% cell
 * renders with the same `err`-toned background every low-accuracy cell
 * gets, but *always* with its percentage printed inside — color is never
 * the only channel telling them apart, the text is: "–" vs "0%".
 *
 * **Interaction:** clicking a ranked topic (in the list below the heatmap,
 * built from `WeaknessChip`) reveals the affected-students panel from that
 * topic's `studentIds`, each linking to `/teacher/students/:studentId`
 * (T-05) — that route doesn't exist until chunk d, so the link 404s for
 * now, same documented state Classes.tsx already carries for T-03's link.
 *
 * **Export:** a CSV of the heatmap matrix (topic rows x student columns,
 * "no data"/"N%" cells) — genuinely cheap client-side from data already in
 * memory, so it's implemented; nothing else on this screen gets an export
 * (a chart-image or full-report export would need more than a Blob + anchor
 * click and isn't attempted here).
 */

type Tone = "ok" | "warn" | "err"

/** One shared accuracy->tone mapping for both the heatmap cells and the
 * ranked-topic `WeaknessChip` severities below it, so the same number never
 * reads as a different tone in two places on the same screen. */
function accuracyTone(accuracy: number): Tone {
  if (accuracy >= 0.75) return "ok"
  if (accuracy >= 0.5) return "warn"
  return "err"
}

const TONE_TO_SEVERITY: Record<Tone, WeaknessSeverity> = {
  ok: "minor",
  warn: "moderate",
  err: "significant",
}

const CELL_TONE_CLASS: Record<Tone, string> = {
  ok: "bg-ok-bg text-ok",
  warn: "bg-warn-bg text-warn",
  err: "bg-err-bg text-err",
}

const GRADE_BAND_BG: Record<string, string> = {
  top: "bg-grade-top",
  mid: "bg-grade-mid",
  borderline: "bg-grade-borderline",
  fail: "bg-grade-fail",
}

function escapeCsvCell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

function downloadHeatmapCsv(
  classLabel: string,
  topics: TopicWeakness[],
  students: { studentId: string; name: string }[],
  cellMap: Map<string, number | null>,
) {
  const header = ["Topic", ...students.map((s) => s.name)]
  const rows = topics.map((t) => [
    t.topic,
    ...students.map((s) => {
      const acc = cellMap.get(`${t.topic}\u0000${s.studentId}`)
      return acc == null ? "No data" : `${Math.round(acc * 100)}%`
    }),
  ])
  const csv = [header, ...rows].map((row) => row.map(escapeCsvCell).join(",")).join("\n")
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `${classLabel.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-heatmap.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function HeatmapCellView({ cell }: { cell: HeatmapCell | undefined }) {
  if (!cell || cell.accuracy == null) {
    return (
      <td className="p-0.5">
        <div
          className="w-11 h-8 flex items-center justify-center rounded bg-surface-2 border border-dashed border-border text-t3 text-[11px]"
          role="img"
          aria-label="No data"
          title="No data — this student has no recorded attempt on this topic"
        >
          –
        </div>
      </td>
    )
  }
  const tone = accuracyTone(cell.accuracy)
  const pct = Math.round(cell.accuracy * 100)
  return (
    <td className="p-0.5">
      <div
        className={cn(
          "w-11 h-8 flex items-center justify-center rounded font-mono text-[11px] font-medium",
          CELL_TONE_CLASS[tone],
        )}
        title={`${pct}% accuracy`}
      >
        {pct}%
      </div>
    </td>
  )
}

export function ClassAnalytics() {
  const { classDetail } = useClassDetailContext()
  const analyticsQuery = useClassAnalytics(classDetail.id)
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null)

  const studentsById = useMemo(
    () => new Map(classDetail.students.map((s) => [s.studentId, s.name])),
    [classDetail.students],
  )

  if (analyticsQuery.isPending) {
    return (
      <div className="flex flex-col gap-6 min-w-0">
        <h2 className="sr-only">Analytics</h2>
        <div role="status" className="text-[13.5px] text-t2">
          Loading analytics…
        </div>
      </div>
    )
  }

  if (analyticsQuery.isError) {
    return (
      <div className="flex flex-col gap-6 min-w-0">
        <h2 className="sr-only">Analytics</h2>
        <ErrorState
          heading="Couldn't load analytics for this class"
          body={analyticsQuery.error.message}
          action={{ label: "Retry", onClick: () => analyticsQuery.refetch() }}
        />
      </div>
    )
  }

  const data = analyticsQuery.data
  const students = classDetail.students.map((s) => ({ studentId: s.studentId, name: s.name }))
  const cellMap = new Map<string, number | null>(
    data.heatmap.map((c) => [`${c.topic}\u0000${c.studentId}`, c.accuracy]),
  )
  const selected = data.topicWeaknesses.find((t) => t.topic === selectedTopic) ?? null
  const maxGradeCount = Math.max(1, ...data.gradeDistribution.map((b) => b.count))
  const latestTrendPoint = data.trend.at(-1) ?? null

  return (
    <div className="flex flex-col gap-8 min-w-0">
      <h2 className="sr-only">Analytics</h2>

      {/* Centrepiece: topic x student weakness heatmap */}
      <section className="flex flex-col gap-3 min-w-0">
        <div className="flex items-end justify-between gap-3 flex-wrap gap-y-2">
          <div>
            <div className="font-serif text-[24px]">Topic weakness heatmap</div>
            <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mt-1">
              Ranked by class-wide marks lost — what to teach next week
            </div>
          </div>
          {data.topicWeaknesses.length > 0 ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => downloadHeatmapCsv(classDetail.label, data.topicWeaknesses, students, cellMap)}
            >
              <DownloadSimple size={14} aria-hidden />
              Export CSV
            </Button>
          ) : null}
        </div>

        {data.topicWeaknesses.length === 0 ? (
          <EmptyState
            heading="No weakness data yet"
            body="Once students submit graded papers or quizzes, topics they lose marks on will rank here."
          />
        ) : (
          <div
            className="bg-surface border border-border rounded-[14px] p-3 overflow-x-auto min-w-0"
            tabIndex={0}
            role="region"
            aria-label="Topic weakness heatmap, scrollable horizontally"
          >
            <table className="border-collapse">
              <caption className="sr-only">
                Topic accuracy by student. Blank cells with a dash mean no recorded attempt, not a
                zero score.
              </caption>
              <thead>
                <tr>
                  <th scope="col" className="sticky left-0 bg-surface px-2 py-1.5 text-left align-bottom">
                    <span className="sr-only">Topic</span>
                  </th>
                  {students.map((s) => (
                    <th
                      key={s.studentId}
                      scope="col"
                      className="px-0.5 py-1.5 align-bottom"
                      title={s.name}
                    >
                      <span
                        className="block w-11 font-mono text-[9.5px] text-t3 truncate"
                        style={{ writingMode: "vertical-rl" }}
                      >
                        {s.name}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.topicWeaknesses.map((t) => (
                  <tr key={t.topic}>
                    <th
                      scope="row"
                      className="sticky left-0 bg-surface px-2 py-1 text-left text-[12.5px] font-normal whitespace-nowrap max-w-[180px] truncate"
                      title={t.topic}
                    >
                      {t.topic}
                    </th>
                    {students.map((s) => (
                      <HeatmapCellView
                        key={s.studentId}
                        cell={data.heatmap.find(
                          (c) => c.topic === t.topic && c.studentId === s.studentId,
                        )}
                      />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Ranked topic list — click to drill into affected students (-> T-05) */}
        {data.topicWeaknesses.length > 0 ? (
          <div className="flex flex-col gap-2 mt-1">
            {data.topicWeaknesses.map((t) => (
              <WeaknessChip
                key={t.topic}
                variant="list"
                topic={t.topic}
                severity={TONE_TO_SEVERITY[accuracyTone(t.accuracy)]}
                meta={`${t.lostMarks}/${t.maximumMarks} marks lost across the class · ${Math.round(t.accuracy * 100)}% accuracy`}
                onClick={() => setSelectedTopic((cur) => (cur === t.topic ? null : t.topic))}
                aria-expanded={selectedTopic === t.topic}
              />
            ))}
          </div>
        ) : null}

        {selected ? (
          <div className="bg-surface-2 border border-border rounded-lg p-4 flex flex-col gap-2.5">
            <div className="text-[13.5px] font-medium">
              Students affected by "{selected.topic}"
            </div>
            {selected.studentIds.length === 0 ? (
              <div className="text-[12.5px] text-t2">No individual students identified.</div>
            ) : (
              <ul className="flex flex-wrap gap-2 list-none p-0 m-0">
                {selected.studentIds.map((id) => (
                  <li key={id}>
                    <Link
                      to={`/teacher/students/${id}`}
                      className="inline-flex items-center border border-border bg-surface rounded-full px-3 py-1 text-[12.5px] text-t1 hover:underline"
                    >
                      {studentsById.get(id) ?? id}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </section>

      {/* Grade distribution */}
      <section className="flex flex-col gap-3">
        <div className="font-serif text-[22px]">Grade distribution</div>
        <div className="bg-surface border border-border rounded-[14px] p-[18px] flex flex-col gap-2.5">
          {data.gradeDistribution.map((b) => (
            <div key={b.grade} className="flex items-center gap-3">
              <div className="w-6 font-mono text-[12.5px] text-t2 flex-none">{b.grade}</div>
              <div className="flex-1 h-4 bg-surface-2 rounded-full overflow-hidden min-w-0">
                <div
                  className={cn("h-full rounded-full", GRADE_BAND_BG[gradeBand(b.grade)])}
                  style={{ width: `${(b.count / maxGradeCount) * 100}%` }}
                />
              </div>
              <div className="w-8 text-right font-mono text-[12.5px] text-t2 flex-none">
                {b.count}
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 min-w-0">
        {/* Cohort trend */}
        <section className="flex flex-col gap-3 min-w-0">
          <div className="font-serif text-[22px]">Performance over time</div>
          <div className="bg-surface border border-border rounded-[14px] p-[18px] flex flex-col gap-3 min-w-0">
            {data.trend.length === 0 ? (
              <div className="text-[13px] text-t2">No graded submissions yet.</div>
            ) : (
              <>
                <div className="flex items-center gap-3 flex-wrap">
                  <TrendSparkline values={data.trend.map((p) => p.meanPercentage)} width={120} />
                  {latestTrendPoint ? (
                    <div className="text-[12.5px] text-t2">
                      Latest: {Math.round(latestTrendPoint.meanPercentage)}% mean, over{" "}
                      {latestTrendPoint.sampleSize} student
                      {latestTrendPoint.sampleSize === 1 ? "" : "s"}
                    </div>
                  ) : null}
                </div>
                <div
                  className="max-h-[180px] overflow-y-auto border-t border-border pt-2 -mx-1"
                  tabIndex={0}
                  role="region"
                  aria-label="Cohort mean percentage over time, scrollable"
                >
                  <table className="w-full text-[12px] border-collapse">
                    <caption className="sr-only">Cohort mean percentage over time</caption>
                    <thead>
                      <tr className="text-t3">
                        <th scope="col" className="text-left font-mono text-[10px] uppercase tracking-[0.08em] px-1 py-1">
                          Date
                        </th>
                        <th scope="col" className="text-right font-mono text-[10px] uppercase tracking-[0.08em] px-1 py-1">
                          Mean
                        </th>
                        <th scope="col" className="text-right font-mono text-[10px] uppercase tracking-[0.08em] px-1 py-1">
                          Students
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.trend.map((p) => (
                        <tr key={p.timestamp} className="border-t border-border">
                          <td className="px-1 py-1 text-t2">
                            {new Date(p.timestamp).toLocaleDateString(undefined, {
                              year: "numeric",
                              month: "short",
                              day: "numeric",
                            })}
                          </td>
                          <td className="px-1 py-1 text-right font-mono">
                            {Math.round(p.meanPercentage)}%
                          </td>
                          <td className="px-1 py-1 text-right font-mono text-t3">
                            {p.sampleSize}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </section>

        {/* Engagement */}
        <section className="flex flex-col gap-3 min-w-0">
          <div className="font-serif text-[22px]">Engagement</div>
          <div className="bg-surface border border-border rounded-[14px] p-[18px] grid grid-cols-2 gap-4">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                Submissions, 7 days
              </div>
              <div className="font-serif text-[26px] mt-1">{data.engagement.submissionsLast7Days}</div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                Submissions, 30 days
              </div>
              <div className="font-serif text-[26px] mt-1">{data.engagement.submissionsLast30Days}</div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                Active students, 7 days
              </div>
              <div className="font-serif text-[26px] mt-1">{data.engagement.activeStudentsLast7Days}</div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                Active students, 30 days
              </div>
              <div className="font-serif text-[26px] mt-1">{data.engagement.activeStudentsLast30Days}</div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                Never active
              </div>
              <div className="font-serif text-[26px] mt-1">{data.engagement.neverActiveCount}</div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                Median days since last submission
              </div>
              <div className="font-serif text-[26px] mt-1">
                {data.engagement.medianDaysSinceLastSubmission != null
                  ? Math.round(data.engagement.medianDaysSinceLastSubmission)
                  : "—"}
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* Per-paper comparison */}
      <section className="flex flex-col gap-3 min-w-0">
        <div className="font-serif text-[22px]">Per-paper comparison</div>
        {data.paperComparison.length === 0 ? (
          <div className="text-[13px] text-t2">No papers recorded for this class yet.</div>
        ) : (
          <div
            className="bg-surface border border-border rounded-[14px] overflow-hidden overflow-x-auto min-w-0"
            tabIndex={0}
            role="region"
            aria-label="Per-paper comparison, scrollable horizontally"
          >
            <table className="w-full text-[13px] border-collapse">
              <caption className="sr-only">Cohort stats per paper</caption>
              <thead>
                <tr className="bg-[oklch(0.965_0.012_78)] border-b border-border">
                  <th scope="col" className="text-left px-4 py-2.5 font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                    Paper
                  </th>
                  <th scope="col" className="text-right px-4 py-2.5 font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                    Mean
                  </th>
                  <th scope="col" className="text-right px-4 py-2.5 font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                    Attempts
                  </th>
                  <th scope="col" className="text-right px-4 py-2.5 font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                    Students
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.paperComparison.map((p) => (
                  <tr key={p.paperId} className="border-b border-border last:border-b-0">
                    <td className="px-4 py-2.5 font-mono text-[12.5px]">
                      {p.subjectCode} · Paper {p.paperNumber} Variant {p.paperVariant}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[12.5px]">
                      {Math.round(p.meanPercentage)}%
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[12.5px]">
                      {p.attemptCount}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[12.5px]">
                      {p.studentCount}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

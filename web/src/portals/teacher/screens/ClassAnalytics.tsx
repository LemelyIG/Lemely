/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { DownloadSimple } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { ChartFrame } from "@/components/ui/chart-frame"
import { LineChart } from "@/components/ui/line-chart"
import { BarChart } from "@/components/ui/bar-chart"
import { WeaknessChip } from "@/components/ui/weakness-chip"
import { gradeBand } from "@/components/ui/grade-badge"
import { useNivoTheme } from "@/lib/nivoTheme"
import { cn, downloadCsv } from "@/lib/utils"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { teacherLoadFailureMessage } from "@/lib/teacherOutcome"
import { accuracyTone, TONE_CLASS, TONE_TO_SEVERITY } from "@/lib/severity"
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
 * `gradeDistribution` the grade bars; `trend` the cohort line;
 * `paperComparison` the per-paper table; `engagement` the activity stats.
 *
 * P5.3 put both of the plots on Nivo and the shared chart theme (DESIGN.md
 * §11) — see `GradeDistributionPanel` and `CohortTrendPanel` below, each of
 * which documents what changed and why. The heatmap deliberately did NOT
 * move: it is a labelled matrix of cells, every one of which prints its own
 * value, and its no-data-vs-0% distinction (see above) is the single thing on
 * this screen that must not be got wrong. Nivo's heatmap has no notion of that
 * distinction, so putting it there would trade the one guarantee this panel
 * exists to make for a nicer transition. Logged as a §11 exception.
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

/**
 * The resolved token each grade band's bar is drawn in.
 *
 * The names, not the values — `useNivoTheme()` resolves them, for the reason
 * `lib/nivoTheme.ts` sets out at length (Nivo hands a bar colour to
 * react-spring, which parses it, so a `var()` string arrives as nothing).
 *
 * These are `--grade-*`, not `SERIES_TOKENS`. A grade distribution's colour is
 * not a series key: it is the same four-band scale the `GradeBadge` on every
 * other teacher screen uses, and it is the one colour relationship in this
 * product a teacher genuinely learns. Recolouring it from the categorical
 * palette would make the bars prettier and the page less legible.
 */
const GRADE_BAND_TOKEN: Record<string, string> = {
  top: "--grade-top",
  mid: "--grade-mid",
  borderline: "--grade-borderline",
  fail: "--grade-fail",
}

/**
 * Grade distribution (`gradeDistribution`), as a horizontal bar per grade.
 *
 * **The empty test is "every count is zero", not "no rows".** `grade_distribution`
 * returns *every* rung of the subject's grade ladder with zero counts included, precisely so
 * a frontend never has to infer "nobody on a B" from a missing key — which
 * means `length === 0` is unreachable and a class with nothing marked yet drew
 * a full ladder of empty tracks with a 0 beside each. That is a blank chart
 * wearing a chart's clothes, and §11 makes the empty state mandatory. The
 * momentum panel on the student dashboard hit the same shape in P4.1 and keys
 * off its own emptiness the same way.
 *
 * Horizontal, because the categories are grades and the value is a headcount:
 * a reader scans the grade ladder vertically, in the order it is taught.
 */
function GradeDistributionPanel({
  buckets,
}: {
  buckets: readonly { grade: string; count: number }[]
}) {
  const { tokens } = useNivoTheme()
  const total = buckets.reduce((sum, b) => sum + b.count, 0)

  return (
    <ChartFrame
      title="Grade distribution"
      subtitle="Students by their latest paper grade"
      isEmpty={total === 0}
      emptyMarginalia="No grades yet"
      emptyBody="Every student on this class ladder appears here once they have a marked paper. Nobody in this class has one so far."
    >
      <BarChart
        /*
         * Reversed, because Nivo lays a horizontal bar chart out from the
         * bottom up and the served ladder runs highest-first. Unreversed, the
         * ladder rendered with A* at the floor and U at the ceiling — upside
         * down against every other place a teacher meets these grades, and
         * against the way the ladder is spoken.
         */
        data={[...buckets].reverse().map((b) => ({ label: b.grade, value: b.count }))}
        horizontal
        showValues
        height={Math.max(180, buckets.length * 26)}
        axisBottomLegend="Students"
        colorFor={(point) => tokens[GRADE_BAND_TOKEN[gradeBand(point.label)]] ?? ""}
        formatValue={(v) => String(Math.round(v))}
        tooltipDetail={(point) =>
          total === 0
            ? null
            : `${Math.round((point.value / total) * 100)}% of the ${total} graded student${
                total === 1 ? "" : "s"
              }`
        }
        ariaLabel="Grade distribution: number of students on each grade"
      />
    </ChartFrame>
  )
}

/**
 * Cohort mean percentage over time (`trend`), the panel §5.3 singles out for
 * the full treatment: animated entry, hover tooltips with exact values, a real
 * axis, and an empty state.
 *
 * What it replaces is a 120px `TrendSparkline` — six pixels per point, no
 * scale, no dates, and `sampleSize` shown for the final point only. That last
 * one is the substantive gain: an early point in a class's life can rest on two
 * students, and a cohort line that does not say so invites a teacher to read a
 * two-student mean as a class-wide dip. Every point now carries its sample size
 * in the tooltip and in its accessible label.
 *
 * The table below the chart stays. It is not redundancy: it is the exact-value,
 * copy-pasteable, screen-reader-native channel, and a chart is a summary of it
 * rather than a replacement for it.
 */
function CohortTrendPanel({
  trend,
}: {
  trend: readonly { timestamp: string; meanPercentage: number; sampleSize: number }[]
}) {
  const latest = trend.at(-1) ?? null

  /*
   * `TrendPointDTO` also carries a `label`, and it is deliberately NOT used
   * here: the backend sets it to the raw `recorded_at` UTC ISO string verbatim
   * (its own docstring says so, and says the frontend may reformat), so
   * rendering the field named "label" would put `2026-03-04T11:52:07Z` on a
   * teacher's x-axis. The timestamp is the truth; the reading of it belongs on
   * this side.
   */
  const series = useMemo(
    () => [
      {
        id: "Cohort mean",
        data: trend.map((p) => ({
          x: new Date(p.timestamp).toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
          }),
          y: p.meanPercentage,
        })),
      },
    ],
    [trend],
  )

  const sampleByLabel = useMemo(() => {
    const map = new Map<string, number>()
    for (const [i, p] of trend.entries()) map.set(series[0].data[i].x, p.sampleSize)
    return map
  }, [trend, series])

  return (
    <ChartFrame
      title="Performance over time"
      subtitle="Cohort mean percentage, one point per submission"
      isEmpty={trend.length === 0}
      emptyMarginalia="Nothing marked yet"
      emptyBody="The cohort line starts drawing itself the first time a paper in this class is marked."
    >
      <LineChart
        series={series}
        height={200}
        enableArea
        /*
         * Pinned 0–100 rather than auto. A cohort sitting between 71% and 74%
         * on an auto domain fills the panel top to bottom and reads as
         * volatility; on a percentage axis it reads as what it is, which is a
         * steady class.
         */
        yMin={0}
        yMax={100}
        formatValue={(v) => `${Math.round(v)}%`}
        tooltipDetail={(point) => {
          const n = sampleByLabel.get(point.x)
          if (n === undefined) return null
          return `over ${n} student${n === 1 ? "" : "s"}`
        }}
        ariaLabel="Cohort mean percentage over time"
      />
      {latest ? (
        <div className="text-body-sm text-ink-muted">
          Latest: {Math.round(latest.meanPercentage)}% mean, over {latest.sampleSize} student
          {latest.sampleSize === 1 ? "" : "s"}
        </div>
      ) : null}
      <div
        className="-mx-1 max-h-[180px] overflow-y-auto border-t border-rule pt-2"
        tabIndex={0}
        role="region"
        aria-label="Cohort mean percentage over time, scrollable"
      >
        <table className="w-full border-collapse">
          <caption className="sr-only">Cohort mean percentage over time</caption>
          <thead>
            <tr className="text-ink-faint">
              <th scope="col" className="px-1 py-1 text-start text-eyebrow">
                Date
              </th>
              <th scope="col" className="px-1 py-1 text-end text-eyebrow">
                Mean
              </th>
              <th scope="col" className="px-1 py-1 text-end text-eyebrow">
                Students
              </th>
            </tr>
          </thead>
          <tbody>
            {trend.map((p) => (
              <tr key={p.timestamp} className="border-t border-rule">
                <td className="px-1 py-1 text-body-sm text-ink-muted">
                  {new Date(p.timestamp).toLocaleDateString(undefined, {
                    year: "numeric",
                    month: "short",
                    day: "numeric",
                  })}
                </td>
                <td className="px-1 py-1 text-end text-data-sm text-ink">
                  {Math.round(p.meanPercentage)}%
                </td>
                <td className="px-1 py-1 text-end text-data-sm text-ink-faint">
                  {p.sampleSize}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ChartFrame>
  )
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
  downloadCsv(`${classLabel}-heatmap`, [header, ...rows])
}

function HeatmapCellView({ cell }: { cell: HeatmapCell | undefined }) {
  if (!cell || cell.accuracy == null) {
    return (
      <td className="p-0.5">
        <div
          className="w-11 h-8 flex items-center justify-center rounded bg-paper-sunk border border-dashed border-rule text-ink-faint text-data-sm"
          role="img"
          aria-label="No data"
          title="No data. This student has no recorded attempt on this topic"
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
          "w-11 h-8 flex items-center justify-center rounded text-data-sm",
          TONE_CLASS[tone],
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

  return (
    <div className="flex flex-col gap-8 min-w-0">
      {/*
       * A tab panel nested under `ClassDetail.tsx`'s own route, not a whole
       * screen — that parent already renders the page's one visible `<h1>`
       * (the class name), so this stays the plain `h2` it always was rather
       * than taking `QueryState`'s `srHeading` (which always renders an
       * `h1`, per that recipe step's own note that a panel gets no
       * `srHeading`). Kept outside `<QueryState>` so it announces in every
       * state — pending, idle, error, and loaded — the way it did before.
       */}
      <h2 className="sr-only">Analytics</h2>
      <QueryState
        query={analyticsQuery}
        skeleton={
          // Five panels are about to appear, so three panel shapes reserve
          // meaningful space rather than one line of text collapsing the
          // page to a row. §12: the loading state matches the layout it
          // replaces.
          <>
            <PanelSkeleton />
            <PanelSkeleton />
            <PanelSkeleton />
          </>
        }
        /*
         * `useClassAnalytics` disables itself (`enabled: !!classId`), but
         * this screen only ever mounts nested under `ClassDetail.tsx`'s
         * route, which supplies a real `classDetail.id` through context
         * before rendering it — so `idle` is unreachable in practice.
         * Included anyway per the hook's own contract rather than assuming
         * the parent route always will.
         */
        idle={
          <EmptyState heading="No class selected" body="Open a class to see its analytics." />
        }
        error={{
          heading: "Couldn't load analytics for this class",
          body: teacherLoadFailureMessage,
        }}
      >
        {(data) => {
          const students = classDetail.students.map((s) => ({ studentId: s.studentId, name: s.name }))
          const cellMap = new Map<string, number | null>(
            data.heatmap.map((c) => [`${c.topic}\u0000${c.studentId}`, c.accuracy]),
          )
          const selected = data.topicWeaknesses.find((t) => t.topic === selectedTopic) ?? null

          return (
            <>
              {/* Centrepiece: topic x student weakness heatmap */}
              <section className="flex flex-col gap-3 min-w-0">
                <div className="flex items-end justify-between gap-3 flex-wrap gap-y-2">
                  <div>
                    <div className="text-display-md text-ink">Topic weakness heatmap</div>
                    <div className="text-eyebrow text-ink-faint mt-1">
                      Ranked by class-wide marks lost, so you can see what to teach next week
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
                    className="bg-paper-raised border border-rule rounded-lg p-3 overflow-x-auto min-w-0"
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
                          <th scope="col" className="sticky start-0 bg-paper-raised px-2 py-1.5 text-start align-bottom">
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
                                className="block w-11 text-data-sm text-ink-faint truncate"
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
                              className="sticky start-0 bg-paper-raised px-2 py-1 text-start text-body-sm font-normal whitespace-nowrap max-w-[180px] truncate"
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
                  <div className="bg-paper-sunk border border-rule rounded-lg p-4 flex flex-col gap-2.5">
                    <div className="text-body-lg font-medium text-ink">
                      Students affected by "{selected.topic}"
                    </div>
                    {selected.studentIds.length === 0 ? (
                      <div className="text-body-sm text-ink-muted">No individual students identified.</div>
                    ) : (
                      <ul className="flex flex-wrap gap-2 list-none p-0 m-0">
                        {selected.studentIds.map((id) => (
                          <li key={id}>
                            <Link
                              to={`/teacher/students/${id}`}
                              className="inline-flex items-center border border-rule bg-paper-raised rounded-md px-3 py-1 text-body-sm text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
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

              <GradeDistributionPanel buckets={data.gradeDistribution} />

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 min-w-0">
                <CohortTrendPanel trend={data.trend} />

                {/* Engagement */}
                <section className="flex flex-col gap-3 min-w-0">
                  <div className="text-display-md text-ink">Engagement</div>
                  <div className="bg-paper-raised border border-rule rounded-lg p-6 grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-eyebrow text-ink-faint">
                        Submissions, 7 days
                      </div>
                      <div className="text-data-lg text-ink mt-1">{data.engagement.submissionsLast7Days}</div>
                    </div>
                    <div>
                      <div className="text-eyebrow text-ink-faint">
                        Submissions, 30 days
                      </div>
                      <div className="text-data-lg text-ink mt-1">{data.engagement.submissionsLast30Days}</div>
                    </div>
                    <div>
                      <div className="text-eyebrow text-ink-faint">
                        Active students, 7 days
                      </div>
                      <div className="text-data-lg text-ink mt-1">{data.engagement.activeStudentsLast7Days}</div>
                    </div>
                    <div>
                      <div className="text-eyebrow text-ink-faint">
                        Active students, 30 days
                      </div>
                      <div className="text-data-lg text-ink mt-1">{data.engagement.activeStudentsLast30Days}</div>
                    </div>
                    <div>
                      <div className="text-eyebrow text-ink-faint">
                        Never active
                      </div>
                      <div className="text-data-lg text-ink mt-1">{data.engagement.neverActiveCount}</div>
                    </div>
                    <div>
                      <div className="text-eyebrow text-ink-faint">
                        Median days since last submission
                      </div>
                      <div className="text-data-lg text-ink mt-1">
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
                <div className="text-display-md text-ink">Per-paper comparison</div>
                {data.paperComparison.length === 0 ? (
                  <div className="text-body-md text-ink-muted">No papers recorded for this class yet.</div>
                ) : (
                  <div
                    className="bg-paper-raised border border-rule rounded-lg overflow-hidden overflow-x-auto min-w-0"
                    tabIndex={0}
                    role="region"
                    aria-label="Per-paper comparison, scrollable horizontally"
                  >
                    <table className="w-full text-body-md border-collapse">
                      <caption className="sr-only">Cohort stats per paper</caption>
                      <thead>
                        <tr className="bg-paper-sunk border-b border-rule">
                          <th scope="col" className="text-start px-4 py-2.5 text-eyebrow text-ink-faint">
                            Paper
                          </th>
                          <th scope="col" className="text-end px-4 py-2.5 text-eyebrow text-ink-faint">
                            Mean
                          </th>
                          <th scope="col" className="text-end px-4 py-2.5 text-eyebrow text-ink-faint">
                            Attempts
                          </th>
                          <th scope="col" className="text-end px-4 py-2.5 text-eyebrow text-ink-faint">
                            Students
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.paperComparison.map((p) => (
                          <tr key={p.paperId} className="border-b border-rule last:border-b-0">
                            <td className="px-4 py-2.5 text-data-sm text-ink">
                              {p.subjectCode} · Paper {p.paperNumber} Variant {p.paperVariant}
                            </td>
                            <td className="px-4 py-2.5 text-end text-data-sm text-ink">
                              {Math.round(p.meanPercentage)}%
                            </td>
                            <td className="px-4 py-2.5 text-end text-data-sm text-ink">
                              {p.attemptCount}
                            </td>
                            <td className="px-4 py-2.5 text-end text-data-sm text-ink">
                              {p.studentCount}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )
        }}
      </QueryState>
    </div>
  )
}

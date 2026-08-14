/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { GradeBadge } from "@/components/ui/grade-badge"
import { ErrorState } from "@/components/ui/state-views"
import { ChartFrame } from "@/components/ui/chart-frame"
import { LineChart } from "@/components/ui/line-chart"
import { WeaknessChip, type WeaknessSeverity } from "@/components/ui/weakness-chip"
import { relativeTime } from "@/lib/utils"
import { useStudentDetail } from "@/lib/hooks/useTeacherApi"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { teacherLoadFailureMessage } from "@/lib/teacherOutcome"
import type { StudentWeakness } from "@/lib/teacherTypes"

/*
 * Student detail, teacher view (T-05). `GET /teacher/students/{studentId}`
 * (`useStudentDetail()`) is the single fetch — every panel below is a direct
 * projection of one `StudentDetailDTO` field, never a client-side
 * recomputation:
 *
 *  - Subjects & predicted grades  -> `subjects` (`GradeBadge basis="predicted"`,
 *    same convention as T-03's roster column — this DTO's own docstring says
 *    `predictedGrade` IS the app's "predicted grade" notion, not a second one).
 *  - Full attempt history          -> `attempts`, newest first (already
 *    ordered by the backend).
 *  - Weakness list with evidence   -> `weaknesses`, each rendered through
 *    `WeaknessChip` with its lost/maximum marks and accuracy as the `meta`
 *    line — the evidence, not a verdict (spec §1.4).
 *  - Trend chart                   -> `trend` (this student's own percentage
 *    series, chronological) via `LineChart` + an accessible table underneath,
 *    same pattern `ClassAnalytics` uses for the cohort trend. P5.3 moved both
 *    off `TrendSparkline` onto Nivo and the shared chart theme (DESIGN.md
 *    §11); see `StudentTrendPanel` below.
 *  - At-risk status and reason     -> `isAtRisk`/`atRiskFlags`, each flag's
 *    real `summary` sentence rendered directly, acknowledged flags tagged
 *    and never hidden (D3.5). Display only here, same as T-03's roster — the
 *    acknowledge *action* lives on T-06.
 *  - Activity/engagement           -> `engagement`.
 *
 * **Integrity signals are deliberately absent from this screen.** The spec
 * asks for them "phrased neutrally... never presented as a conclusion", but
 * `StudentDetailDTO` carries no such field at all (verified against
 * `lemely/web/schemas_analytics.py` and the router's own docstring, D3.4): a
 * persisted history record has only totals/weak-areas/metadata, never the
 * per-question answers plagiarism/AI-content checks need. There is nothing
 * honest to render, so nothing renders — no stub panel, no placeholder, no
 * "not available" note standing in for a real signal. Reported as an absent
 * field, not fixed here (adding it would be a backend change out of scope).
 *
 * **"Open any attempt" (S-15/16/17 teacher view + remark) and "assign
 * practice" have no route yet** — remark lands with T-08 (P3.8), practice
 * assignment with P4. Per the established precedent (`Overview.tsx`,
 * `ClassRoster.tsx`), both render as visibly disabled controls with a
 * "Coming soon" tag rather than a dead link or a silently-inert button.
 * "Contact route if the school configures one" is omitted entirely, not
 * disabled — there is no school-contact-config field anywhere to gate a
 * disabled control on, so unlike the two deferred *features* above this is
 * an absent *data source*, same category as the integrity signals.
 */

function subjectPercent(latestPercentage: number): string {
  return `${Math.round(latestPercentage)}%`
}

function accuracyTone(accuracy: number): WeaknessSeverity {
  if (accuracy >= 0.75) return "minor"
  if (accuracy >= 0.5) return "moderate"
  return "significant"
}

function WeaknessRow({ weakness }: { weakness: StudentWeakness }) {
  return (
    <WeaknessChip
      variant="list"
      topic={weakness.topic}
      severity={accuracyTone(weakness.accuracy)}
      meta={`${weakness.lostMarks}/${weakness.maximumMarks} marks lost · ${Math.round(
        weakness.accuracy * 100,
      )}% accuracy${weakness.questionIds.length > 0 ? ` · ${weakness.questionIds.length} question${weakness.questionIds.length === 1 ? "" : "s"}` : ""}`}
    />
  )
}

/**
 * This student's own percentage series (`trend`), on the shared chart theme.
 *
 * The teacher-facing sibling of `ClassAnalytics`'s `CohortTrendPanel`, and it
 * is the "at-risk trends" chart §5.3 names: the panel a teacher opens *because*
 * a student was flagged, to see whether the flag describes a slide or a single
 * bad morning. A 140px sparkline could not answer that question — it had no
 * scale, no dates, and no way to tell a drop from 90 to 80 apart from a drop
 * from 40 to 30.
 *
 * The axis is pinned 0–100 for the same reason the cohort line is: on an auto
 * domain, three papers within four points of each other fill the panel and
 * read as a collapse.
 *
 * The table underneath stays, unchanged, as the exact-value channel.
 */
function StudentTrendPanel({
  trend,
}: {
  trend: readonly { recordedAt: string; percentage: number }[]
}) {
  const series = [
    {
      id: "Percentage",
      data: trend.map((p) => ({
        x: new Date(p.recordedAt).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        }),
        y: p.percentage,
      })),
    },
  ]

  return (
    <ChartFrame
      title="Performance over time"
      subtitle="Percentage per marked paper"
      isEmpty={trend.length === 0}
      emptyMarginalia="No graded papers yet"
      emptyBody="This line starts once this student has a marked paper. Until then there is nothing to read a trend from, and a flat line would imply there was."
    >
      <LineChart
        series={series}
        height={200}
        enableArea
        yMin={0}
        yMax={100}
        formatValue={(v) => `${Math.round(v)}%`}
        ariaLabel="This student's percentage per marked paper, over time"
      />
      <div
        className="-mx-1 max-h-[180px] overflow-y-auto border-t border-rule pt-2"
        tabIndex={0}
        role="region"
        aria-label="Percentage over time, scrollable"
      >
        <table className="w-full border-collapse text-body-sm">
          <caption className="sr-only">This student's percentage over time</caption>
          <thead>
            <tr className="text-ink-faint">
              <th scope="col" className="px-1 py-1 text-start text-eyebrow">
                Date
              </th>
              <th scope="col" className="px-1 py-1 text-end text-eyebrow">
                Percentage
              </th>
            </tr>
          </thead>
          <tbody>
            {trend.map((p) => (
              <tr key={p.recordedAt} className="border-t border-rule">
                <td className="px-1 py-1 text-ink-muted">
                  {new Date(p.recordedAt).toLocaleDateString(undefined, {
                    year: "numeric",
                    month: "short",
                    day: "numeric",
                  })}
                </td>
                <td className="px-1 py-1 text-end text-data-sm text-ink">
                  {Math.round(p.percentage)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ChartFrame>
  )
}

export function StudentDetail() {
  const { studentId } = useParams<{ studentId: string }>()
  const navigate = useNavigate()
  const detailQuery = useStudentDetail(studentId)

  if (detailQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Student detail</h1>
        <PanelSkeleton />
        <PanelSkeleton />
      </div>
    )
  }

  if (detailQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Student detail</h1>
        <ErrorState
          heading="Couldn't load this student"
          body={teacherLoadFailureMessage(detailQuery.error)}
          action={{ label: "Retry", onClick: () => detailQuery.refetch() }}
          secondaryAction={{ label: "Go back", onClick: () => navigate(-1) }}
        />
      </div>
    )
  }

  const student = detailQuery.data

  return (
    <div className="lm-screen flex flex-col gap-8 min-w-0">
      <div className="flex flex-col gap-1">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="text-body-sm text-ink-faint hover:text-ink w-fit bg-transparent border-0 p-0 cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          ← Back
        </button>
        <div className="flex items-start gap-4 flex-wrap gap-y-2 mt-1">
          <div className="min-w-0">
            <h1 className="text-display-md mt-1.5 text-pretty">
              {student.displayName}
            </h1>
            <div className="text-body-sm text-ink-muted mt-1">
              {student.engagement.totalPapers} paper
              {student.engagement.totalPapers === 1 ? "" : "s"} recorded ·{" "}
              {student.engagement.lastActiveAt
                ? `active ${relativeTime(student.engagement.lastActiveAt)}`
                : "never active"}
            </div>
          </div>
          <div className="flex-1" />
          {student.isAtRisk ? (
            <Chip tone="err">At risk</Chip>
          ) : (
            <Chip tone="ok">Not currently flagged</Chip>
          )}
        </div>
      </div>

      {/* At-risk status and reason */}
      {student.atRiskFlags.length > 0 ? (
        <section className="flex flex-col gap-3">
          <div className="text-display-sm">At-risk flags</div>
          <div className="bg-paper-raised border border-rule rounded-lg p-[18px] flex flex-col gap-3">
            {student.atRiskFlags.map((f) => (
              <div key={f.reason} className="flex items-start gap-2.5 text-body-md text-ink-muted leading-[1.5]">
                <span
                  aria-hidden="true"
                  className="text-err mt-[6px] w-[6px] h-[6px] rounded-full bg-err flex-none"
                />
                <span className="flex-1 text-pretty">{f.summary}</span>
                {f.acknowledged ? (
                  <Chip tone="neutral" className="flex-none">
                    Acknowledged
                  </Chip>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Subjects and predicted grades */}
      <section className="flex flex-col gap-3">
        <div className="text-display-sm">Subjects</div>
        {student.subjects.length === 0 ? (
          <div className="text-body-md text-ink-muted">No subjects recorded yet.</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {student.subjects.map((s) => (
              <div
                key={s.subjectCode}
                className="bg-paper-raised border border-rule rounded-lg p-[18px] flex items-center gap-4"
              >
                <GradeBadge grade={s.predictedGrade} size="medium" basis="predicted" />
                <div className="min-w-0">
                  <div className="text-eyebrow text-ink-faint">
                    {s.subjectCode}
                  </div>
                  <div className="text-body-md text-ink-muted mt-1">
                    {subjectPercent(s.latestPercentage)} latest · {s.paperCount} paper
                    {s.paperCount === 1 ? "" : "s"}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 min-w-0">
        <StudentTrendPanel trend={student.trend} />

        {/* Activity / engagement */}
        <section className="flex flex-col gap-3 min-w-0">
          <div className="text-display-sm">Engagement</div>
          <div className="bg-paper-raised border border-rule rounded-lg p-[18px] grid grid-cols-2 gap-4">
            <div>
              <div className="text-eyebrow text-ink-faint">
                Total papers
              </div>
              <div className="text-display-sm mt-1">{student.engagement.totalPapers}</div>
            </div>
            <div>
              <div className="text-eyebrow text-ink-faint">
                Last active
              </div>
              <div className="text-display-sm mt-1">
                {student.engagement.lastActiveAt
                  ? relativeTime(student.engagement.lastActiveAt)
                  : "Never"}
              </div>
            </div>
            <div>
              <div className="text-eyebrow text-ink-faint">
                Days since last submission
              </div>
              <div className="text-display-sm mt-1">
                {student.engagement.daysSinceLastSubmission ?? "—"}
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* Weakness list with evidence */}
      <section className="flex flex-col gap-3">
        <div className="text-display-sm">Weaknesses</div>
        {student.weaknesses.length === 0 ? (
          <div className="text-body-md text-ink-muted">No weakness data yet.</div>
        ) : (
          <div className="flex flex-col gap-2">
            {student.weaknesses.map((w) => (
              <WeaknessRow key={w.topic} weakness={w} />
            ))}
          </div>
        )}
      </section>

      {/* Full attempt history */}
      <section className="flex flex-col gap-3 min-w-0">
        <div className="text-display-sm">Attempt history</div>
        {student.attempts.length === 0 ? (
          <div className="text-body-md text-ink-muted">No papers recorded yet.</div>
        ) : (
          <div
            className="bg-paper-raised border border-rule rounded-lg overflow-hidden overflow-x-auto min-w-0"
            tabIndex={0}
            role="region"
            aria-label="Attempt history, scrollable horizontally"
          >
            <table className="w-full text-body-md border-collapse">
              <caption className="sr-only">Full attempt history, newest first</caption>
              <thead>
                <tr className="bg-paper-sunk border-b border-rule">
                  <th scope="col" className="text-start px-4 py-2.5 text-eyebrow text-ink-faint">
                    Paper
                  </th>
                  <th scope="col" className="text-end px-4 py-2.5 text-eyebrow text-ink-faint">
                    Marks
                  </th>
                  <th scope="col" className="text-end px-4 py-2.5 text-eyebrow text-ink-faint">
                    Percentage
                  </th>
                  <th scope="col" className="text-start px-4 py-2.5 text-eyebrow text-ink-faint">
                    Grade
                  </th>
                  <th scope="col" className="text-start px-4 py-2.5 text-eyebrow text-ink-faint">
                    Recorded
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {student.attempts.map((a) => (
                  // `AttemptDTO.paperId` is a "human paper identity"
                  // (`{subjectCode}/{paperNumber}{paperVariant}`, no session/
                  // year, no per-attempt id — see `_paper_id` in
                  // `lemely/web/routers/teacher.py`), NOT a unique key: a
                  // student who re-sits the same paper (a realistic
                  // scenario — practice, specimen papers, repeats) has
                  // multiple attempt rows sharing one `paperId`, which
                  // produced a real duplicate-React-key console error when
                  // verified against seeded multi-attempt data. `recordedAt`
                  // (a full ISO timestamp, one per submission) disambiguates.
                  <tr key={`${a.paperId}-${a.recordedAt}`} className="border-b border-rule last:border-b-0">
                    <td className="px-4 py-2.5 text-data-sm whitespace-nowrap">
                      {a.subjectCode} · Paper {a.paperNumber} Variant {a.paperVariant}
                    </td>
                    <td className="px-4 py-2.5 text-end text-data-sm">
                      {a.awardedMarks}/{a.maximumMarks}
                    </td>
                    <td className="px-4 py-2.5 text-end text-data-sm">
                      {Math.round(a.percentage)}%
                    </td>
                    <td className="px-4 py-2.5">
                      <GradeBadge grade={a.grade} size="inline" basis="achieved" />
                    </td>
                    <td className="px-4 py-2.5 text-ink-muted whitespace-nowrap">
                      {relativeTime(a.recordedAt)}
                    </td>
                    <td className="px-4 py-2.5 text-end whitespace-nowrap">
                      <div className="inline-flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled
                          aria-disabled="true"
                          title="Remarking a specific attempt lands with the review-queue remark tool (T-08)"
                        >
                          View / remark
                        </Button>
                        <Chip tone="neutral">Coming soon</Chip>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Actions the spec names but that have no route yet */}
      <section className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            disabled
            aria-disabled="true"
            title="Practice assignment lands in a later phase (P4)"
          >
            Assign practice
          </Button>
          <Chip tone="neutral">Coming soon</Chip>
        </div>
      </section>
    </div>
  )
}

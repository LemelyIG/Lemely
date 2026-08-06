import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { GradeBadge } from "@/components/ui/grade-badge"
import { ErrorState } from "@/components/ui/state-views"
import { TrendSparkline } from "@/components/ui/trend-sparkline"
import { WeaknessChip, type WeaknessSeverity } from "@/components/ui/weakness-chip"
import { relativeTime } from "@/lib/utils"
import { useStudentDetail } from "@/lib/hooks/useTeacherApi"
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
 *    series, chronological) via `TrendSparkline` + an accessible table
 *    underneath, same pattern `ClassAnalytics` uses for the cohort trend.
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

export function StudentDetail() {
  const { studentId } = useParams<{ studentId: string }>()
  const navigate = useNavigate()
  const detailQuery = useStudentDetail(studentId)

  if (detailQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Student detail</h1>
        <div role="status" className="text-[13.5px] text-t2">
          Loading student…
        </div>
      </div>
    )
  }

  if (detailQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Student detail</h1>
        <ErrorState
          heading="Couldn't load this student"
          body={detailQuery.error.message}
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
          className="text-[12px] text-t3 hover:text-t1 w-fit bg-transparent border-0 p-0 cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← Back
        </button>
        <div className="flex items-start gap-4 flex-wrap gap-y-2 mt-1">
          <div className="min-w-0">
            <h1 className="font-serif text-[34px] leading-[1.1] mt-1.5 text-pretty">
              {student.displayName}
            </h1>
            <div className="text-[12.5px] text-t2 mt-1">
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
          <div className="font-serif text-[22px]">At-risk flags</div>
          <div className="bg-surface border border-border rounded-[14px] p-[18px] flex flex-col gap-3">
            {student.atRiskFlags.map((f) => (
              <div key={f.reason} className="flex items-start gap-2.5 text-[13px] text-t2 leading-[1.5]">
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
        <div className="font-serif text-[22px]">Subjects</div>
        {student.subjects.length === 0 ? (
          <div className="text-[13px] text-t2">No subjects recorded yet.</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {student.subjects.map((s) => (
              <div
                key={s.subjectCode}
                className="bg-surface border border-border rounded-[14px] p-[18px] flex items-center gap-4"
              >
                <GradeBadge grade={s.predictedGrade} size="medium" basis="predicted" />
                <div className="min-w-0">
                  <div className="font-mono text-[11px] tracking-[0.08em] uppercase text-t3">
                    {s.subjectCode}
                  </div>
                  <div className="text-[13px] text-t2 mt-1">
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
        {/* Trend chart */}
        <section className="flex flex-col gap-3 min-w-0">
          <div className="font-serif text-[22px]">Performance over time</div>
          <div className="bg-surface border border-border rounded-[14px] p-[18px] flex flex-col gap-3 min-w-0">
            {student.trend.length === 0 ? (
              <div className="text-[13px] text-t2">No graded papers yet.</div>
            ) : (
              <>
                <TrendSparkline values={student.trend.map((p) => p.percentage)} width={140} />
                <div
                  className="max-h-[180px] overflow-y-auto border-t border-border pt-2 -mx-1"
                  tabIndex={0}
                  role="region"
                  aria-label="Percentage over time, scrollable"
                >
                  <table className="w-full text-[12px] border-collapse">
                    <caption className="sr-only">This student's percentage over time</caption>
                    <thead>
                      <tr className="text-t3">
                        <th scope="col" className="text-left font-mono text-[10px] uppercase tracking-[0.08em] px-1 py-1">
                          Date
                        </th>
                        <th scope="col" className="text-right font-mono text-[10px] uppercase tracking-[0.08em] px-1 py-1">
                          Percentage
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {student.trend.map((p) => (
                        <tr key={p.recordedAt} className="border-t border-border">
                          <td className="px-1 py-1 text-t2">
                            {new Date(p.recordedAt).toLocaleDateString(undefined, {
                              year: "numeric",
                              month: "short",
                              day: "numeric",
                            })}
                          </td>
                          <td className="px-1 py-1 text-right font-mono">
                            {Math.round(p.percentage)}%
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

        {/* Activity / engagement */}
        <section className="flex flex-col gap-3 min-w-0">
          <div className="font-serif text-[22px]">Engagement</div>
          <div className="bg-surface border border-border rounded-[14px] p-[18px] grid grid-cols-2 gap-4">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                Total papers
              </div>
              <div className="font-serif text-[26px] mt-1">{student.engagement.totalPapers}</div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                Last active
              </div>
              <div className="font-serif text-[22px] mt-1">
                {student.engagement.lastActiveAt
                  ? relativeTime(student.engagement.lastActiveAt)
                  : "Never"}
              </div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                Days since last submission
              </div>
              <div className="font-serif text-[26px] mt-1">
                {student.engagement.daysSinceLastSubmission ?? "—"}
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* Weakness list with evidence */}
      <section className="flex flex-col gap-3">
        <div className="font-serif text-[22px]">Weaknesses</div>
        {student.weaknesses.length === 0 ? (
          <div className="text-[13px] text-t2">No weakness data yet.</div>
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
        <div className="font-serif text-[22px]">Attempt history</div>
        {student.attempts.length === 0 ? (
          <div className="text-[13px] text-t2">No papers recorded yet.</div>
        ) : (
          <div
            className="bg-surface border border-border rounded-[14px] overflow-hidden overflow-x-auto min-w-0"
            tabIndex={0}
            role="region"
            aria-label="Attempt history, scrollable horizontally"
          >
            <table className="w-full text-[13px] border-collapse">
              <caption className="sr-only">Full attempt history, newest first</caption>
              <thead>
                <tr className="bg-[oklch(0.965_0.012_78)] border-b border-border">
                  <th scope="col" className="text-left px-4 py-2.5 font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                    Paper
                  </th>
                  <th scope="col" className="text-right px-4 py-2.5 font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                    Marks
                  </th>
                  <th scope="col" className="text-right px-4 py-2.5 font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                    Percentage
                  </th>
                  <th scope="col" className="text-left px-4 py-2.5 font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
                    Grade
                  </th>
                  <th scope="col" className="text-left px-4 py-2.5 font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
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
                  <tr key={`${a.paperId}-${a.recordedAt}`} className="border-b border-border last:border-b-0">
                    <td className="px-4 py-2.5 font-mono text-[12.5px] whitespace-nowrap">
                      {a.subjectCode} · Paper {a.paperNumber} Variant {a.paperVariant}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[12.5px]">
                      {a.awardedMarks}/{a.maximumMarks}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[12.5px]">
                      {Math.round(a.percentage)}%
                    </td>
                    <td className="px-4 py-2.5">
                      <GradeBadge grade={a.grade} size="inline" basis="achieved" />
                    </td>
                    <td className="px-4 py-2.5 text-t2 whitespace-nowrap">
                      {relativeTime(a.recordedAt)}
                    </td>
                    <td className="px-4 py-2.5 text-right whitespace-nowrap">
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

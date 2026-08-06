import { useNavigate, Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { GradeBadge } from "@/components/ui/grade-badge"
import { cn, initialsOf, relativeTime } from "@/lib/utils"
import { StatCard } from "../components/StatCard"
import { Avatar } from "../components/Avatar"
import { useTeacherOverview, useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import type { RecentActivity } from "@/lib/teacherTypes"

/*
 * Overview (T-01). Wired to `GET /teacher/overview` (`useTeacherOverview()`)
 * for stats/at-risk/recent-activity, and `GET /teacher/classes`
 * (`useTeacherClasses()`) for the class summary cards — the two round trips
 * the spec's five contents need (`docs/LEMELY_UI_SPEC.md` §4.7 T-01).
 *
 * The five contents and their source:
 *  1. At-risk students, the permanent top item — `atRisk[]`, each flag's
 *     real `summary` sentence rendered directly (spec: "reasons must be
 *     shown, not just a red dot"), acknowledged flags tagged, never hidden
 *     (D3.5).
 *  2. Review queue count — the "Need your eyes" stat card, routing into
 *     `/teacher/review` (T-07); an explicit "nothing needs your eyes" note
 *     when it's zero rather than just a quiet "0".
 *  3. Class summary cards — `ClassSummaryDTO` (chunk a, D3.12): name,
 *     student count, average *mark* (not a predicted grade — see below),
 *     top weakness, and a real "last active" read standing in for "activity
 *     level" (no activity-level field/threshold exists anywhere; a relative
 *     timestamp is the honest substitute, not an invented high/med/low
 *     bucket).
 *  4. Recent activity — `recentActivity[]` (chunk a, D3.12): spans papers
 *     and quizzes; a quiz row's `grade` is `null` by design and rendered as
 *     an honest absence (an origin label), never the student's last paper
 *     grade substituted in.
 *  5. Quick actions — quiz builder (T-09) and announcement composer (T-12)
 *     don't exist yet (P3.8); rendered as visibly disabled buttons with a
 *     "Coming soon" tag, never a button that silently does nothing. "Add a
 *     class" is real — it routes to T-02, where creation lives.
 *
 * Deliberate deviation from the spec's wording (D3.12, reported): "average
 * predicted grade" on the class cards is NOT computed — averaging letter
 * grades invents precision the ladder doesn't support. `average` (mean
 * latest percentage) is rendered and labelled "Average mark" instead.
 *
 * States: no classes yet -> an `EmptyState` routing to class creation
 * (T-02) in place of the card grid. Loading / error are handled per-query
 * before the main render so a failure on one call never hides data the
 * other call already has.
 */

const ORIGIN_LABEL: Record<RecentActivity["origin"], string> = {
  past_paper: "Past paper",
  quiz: "Quiz",
  custom_paper: "Custom paper",
}

export function Overview() {
  const navigate = useNavigate()
  const overviewQuery = useTeacherOverview()
  const classesQuery = useTeacherClasses()

  if (overviewQuery.isPending || classesQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Overview</h1>
        <div role="status" className="text-[13.5px] text-t2">
          Loading overview…
        </div>
      </div>
    )
  }

  if (overviewQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Overview</h1>
        <ErrorState
          heading="Couldn't load the overview"
          body={overviewQuery.error.message}
          action={{ label: "Retry", onClick: () => overviewQuery.refetch() }}
        />
      </div>
    )
  }

  if (classesQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Overview</h1>
        <ErrorState
          heading="Couldn't load your classes"
          body={classesQuery.error.message}
          action={{ label: "Retry", onClick: () => classesQuery.refetch() }}
        />
      </div>
    )
  }

  const { stats, atRisk, recentActivity } = overviewQuery.data
  const classes = classesQuery.data.classes
  const papersGraded = stats.find((s) => s.key === "Papers graded")
  const needsEyes = stats.find((s) => s.key === "Need your eyes")
  const needsEyesCount = needsEyes ? Number(needsEyes.value) : null

  return (
    <div className="lm-screen flex flex-col gap-6 min-w-0">
      <div className="flex items-end gap-5 flex-wrap gap-y-2.5">
        <div>
          <div className="font-mono text-[11px] tracking-[0.11em] uppercase text-t3">
            Helwan Science Centre · Sunday 27 July
          </div>
          <h1 className="font-serif text-[40px] leading-[1.08] mt-2">
            Good morning.
          </h1>
          <div className="text-[14.5px] text-t2 mt-2 max-w-[62ch] text-pretty">
            {papersGraded ? `${papersGraded.value} papers graded so far. ` : ""}
            {needsEyes
              ? `${needsEyes.value} answers want your eyes`
              : ""}
            {atRisk.length > 0
              ? `, and ${atRisk.length} student${atRisk.length === 1 ? "" : "s"} want${
                  atRisk.length === 1 ? "s" : ""
                } your attention.`
              : "."}
          </div>
        </div>
        <div className="flex-1" />
        <Button variant="ink" size="lg" onClick={() => navigate("/teacher/review")}>
          Open review queue →
        </Button>
      </div>

      {/* 1. Needs you — the permanent top item */}
      <div className="bg-surface border border-border rounded-[14px] overflow-hidden max-w-[620px] w-full">
        <div className="px-5 pt-[18px] pb-[13px]">
          <div className="font-serif text-[22px]">Needs you</div>
          <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mt-[5px]">
            Flagged by trajectory, not by one bad day
          </div>
        </div>
        {atRisk.length === 0 ? (
          <div className="border-t border-border px-5 py-[15px] text-[13px] text-ok">
            No students flagged right now.
          </div>
        ) : (
          atRisk.map((r) => (
            <div
              key={r.name}
              className="border-t border-border px-5 py-[15px] flex gap-[13px] items-start"
            >
              <Avatar initials={initialsOf(r.name)} className="w-8 h-8 text-[11.5px]" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-[9px] flex-wrap gap-y-1">
                  <div className="text-[13.5px] font-medium">{r.name}</div>
                  <div className="text-[12px] text-t2">Grade {r.grade}</div>
                  <div className="flex-1" />
                  {r.delta !== null ? (
                    <div
                      className={cn(
                        "font-mono text-[12px]",
                        r.delta < 0 ? "text-err" : r.delta > 0 ? "text-ok" : "text-t2",
                      )}
                    >
                      {r.delta > 0 ? "+" : ""}
                      {Math.round(r.delta)} pts
                    </div>
                  ) : null}
                </div>
                {r.weakTopic ? (
                  <div className="text-[12.5px] text-t2 mt-[5px] leading-[1.45] text-pretty">
                    Weakest topic: {r.weakTopic}
                  </div>
                ) : null}
                {r.flags.length > 0 ? (
                  <div className="flex flex-col gap-[7px] mt-[9px]">
                    {r.flags.map((f) => (
                      <div
                        key={f.reason}
                        className="flex items-start gap-2 text-[12.5px] text-t2 leading-[1.45]"
                      >
                        <span
                          aria-hidden="true"
                          className="text-err mt-[6px] w-[5px] h-[5px] rounded-full bg-err flex-none"
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
                ) : null}
              </div>
            </div>
          ))
        )}
      </div>

      {/* 2. Stat cards, including "Need your eyes" (review queue count) */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {stats.map((s) => (
          <StatCard
            key={s.key}
            stat={{
              k: s.key,
              v: s.value,
              unit: s.unit ?? undefined,
              foot: s.foot ?? undefined,
              valueTone: s.valueTone,
              footTone: s.footTone,
            }}
          />
        ))}
      </div>
      {needsEyesCount === 0 ? (
        <div className="text-[13px] text-ok -mt-2">
          Nothing needs your review right now — good news.
        </div>
      ) : null}

      {/* 3. Class summary cards */}
      <div>
        <div className="font-serif text-[22px] mb-3">Your classes</div>
        {classes.length === 0 ? (
          <EmptyState
            heading="Add your first class"
            body="Create a class to start tracking students, marks, and at-risk flags."
            action={{ label: "Create a class", onClick: () => navigate("/teacher/classes") }}
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {classes.map((c) => (
              <Link
                key={c.id}
                to={`/teacher/classes/${c.id}`}
                className="block bg-surface border border-border rounded-[14px] p-[18px] hover:bg-[oklch(0.985_0.008_78)] transition-colors"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-serif text-[19px]">{c.label}</div>
                    <div className="font-mono text-[11px] text-t3 mt-0.5">
                      {c.subjectCode ?? "No subject set"} · {c.studentCount} student
                      {c.studentCount === 1 ? "" : "s"}
                    </div>
                  </div>
                  {c.atRiskCount ? (
                    <Chip tone="err" className="flex-none">
                      {c.atRiskCount} at risk
                    </Chip>
                  ) : null}
                </div>
                <div className="grid grid-cols-2 gap-3 mt-3">
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                      Average mark
                    </div>
                    <div className="font-serif text-[22px] mt-1">
                      {c.average != null ? `${Math.round(c.average)}%` : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-t3">
                      Top weakness
                    </div>
                    <div className="text-[13px] mt-1 text-pretty">
                      {c.topWeakness ?? "Not enough data yet"}
                    </div>
                  </div>
                </div>
                <div className="text-[11.5px] text-t3 mt-3">
                  {c.lastActivityAt ? `Active ${relativeTime(c.lastActivityAt)}` : "No activity yet"}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* 4. Recent activity */}
      <div className="bg-surface border border-border rounded-[14px] overflow-hidden">
        <div className="px-5 pt-[18px] pb-[13px]">
          <div className="font-serif text-[22px]">Recent activity</div>
          <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mt-[5px]">
            Submissions across your classes
          </div>
        </div>
        {recentActivity.length === 0 ? (
          <div className="border-t border-border px-5 py-[15px] text-[13px] text-t2">
            No submissions yet.
          </div>
        ) : (
          recentActivity.map((a) => (
            <div
              key={`${a.studentId}-${a.subjectCode}-${a.recordedAt}`}
              className="border-t border-border px-5 py-[13px] flex items-center gap-3 flex-wrap gap-y-1.5"
            >
              <Avatar initials={initialsOf(a.studentName)} tone="neutral" className="w-7 h-7 text-[10.5px]" />
              <div className="text-[13px]">{a.studentName}</div>
              <div className="font-mono text-[11.5px] text-t3">{a.subjectCode}</div>
              <div className="flex-1" />
              <div className="font-mono text-[13px]">{Math.round(a.percentage)}%</div>
              {a.grade ? (
                <GradeBadge grade={a.grade} size="inline" basis="achieved" />
              ) : (
                <span className="text-[11px] text-t3 font-mono">{ORIGIN_LABEL[a.origin]}</span>
              )}
              <div className="text-[11px] text-t3 w-[72px] text-right">{relativeTime(a.recordedAt)}</div>
            </div>
          ))
        )}
      </div>

      {/* 5. Quick actions */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <Button variant="secondary" disabled aria-disabled="true" title="Coming in a later release">
            Build a quiz
          </Button>
          <Chip tone="neutral">Coming soon</Chip>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" disabled aria-disabled="true" title="Coming in a later release">
            Post an announcement
          </Button>
          <Chip tone="neutral">Coming soon</Chip>
        </div>
        <Button variant="ink" onClick={() => navigate("/teacher/classes")}>
          + Add a class
        </Button>
      </div>
    </div>
  )
}

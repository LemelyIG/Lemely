import { useNavigate, Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { GradeBadge } from "@/components/ui/grade-badge"
import { GettingStarted } from "@/components/ui/getting-started"
import {
  PageHeaderSkeleton,
  ListSkeleton,
  CardGridSkeleton,
} from "@/components/ui/loading-shapes"
import { cn, greetingFor, relativeTime } from "@/lib/utils"
import { StatCard } from "../components/StatCard"
import { Avatar } from "@/components/ui/avatar"
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
 *  5. Quick actions — all three are real routes. **Corrected in P3.2:** this
 *     note used to read "quiz builder (T-09) and announcement composer (T-12)
 *     don't exist yet (P3.8); rendered as visibly disabled buttons with a
 *     'Coming soon' tag". Both were built after it was written, and the
 *     comment plus the two disabled buttons it described outlived them, so the
 *     dashboard was telling teachers a shipped feature was unavailable while
 *     linking to it from the sidebar. The buttons are enabled and this note is
 *     no longer describing code that exists.
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
 *
 * P3.2 adds a state in front of all of those: a genuinely new account (no
 * classes AND no submissions anywhere) gets the `GettingStarted` view instead
 * of a dashboard of zeroes. P3.3 replaced the loading text with skeletons that
 * match this layout.
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

  // P3.3: skeleton matching the real layout (header, "Needs you" list, class
  // card grid, activity list) rather than one line of "Loading overview…"
  // text. See the same note on the student Overview: the old line reserved a
  // single text row for a screen that renders four stacked regions, so the
  // page jumped every time data landed.
  if (overviewQuery.isPending || classesQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Overview</h1>
        <PageHeaderSkeleton />
        <ListSkeleton rows={3} className="max-w-[620px]" />
        <CardGridSkeleton count={3} />
        <ListSkeleton rows={4} avatar />
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

  const now = new Date()
  const greeting = greetingFor(now.getHours())
  // The reader's own locale and timezone, not a hardcoded English string.
  const today = now.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  })

  /*
   * First run (P3.2): a teacher who has just been given an account.
   *
   * Both conditions are required, and that is deliberate. No classes alone is
   * not proof of a first run — a teacher can archive their last class mid-year
   * and should get their dashboard back, not an onboarding screen. No classes
   * *and* no submissions anywhere is the state only a genuinely new account
   * reaches. Rendering the full dashboard for them means a wall of zeroes and
   * four separate "nothing here yet" panels, which is the grid of empty cards
   * this phase exists to remove.
   *
   * Every step below is `later` except the first, for the same reason as the
   * student screen: nothing this account can query reports whether a teacher
   * has, say, uploaded a mark scheme, and a tick we cannot substantiate is a
   * claim about the reader's own history that we are not entitled to make.
   */
  if (classes.length === 0 && recentActivity.length === 0) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <div>
          <div className="font-mono text-2xs tracking-[0.11em] uppercase text-t3">
            {today}
          </div>
          <h1 className="text-display-lg mt-2">{greeting}.</h1>
        </div>
        <GettingStarted
          heading="Start with one class"
          body="Everything else in Lemely hangs off a class: marking, at-risk flags and the analytics all read from who is in it."
          steps={[
            {
              title: "Create your first class",
              body: "Give it a name and a subject code. You can add students straight away or send them a join link later.",
              status: "now",
              to: "/teacher/classes",
              actionLabel: "Create a class",
            },
            {
              title: "Mark a set of papers",
              body: "Upload scanned scripts and Lemely marks them against the official Cambridge scheme, question by question, with a confidence score on every mark.",
              status: "later",
            },
            {
              title: "Look at what marking flagged",
              body: "Anything the marker was not confident about goes to your review queue instead of being guessed at. That queue is the one place your judgement is actually needed.",
              status: "later",
            },
            {
              title: "Watch for students drifting",
              body: "At-risk flags come from trajectory across several papers, not from one bad afternoon, so they need a few marked papers before they mean anything.",
              status: "later",
            },
          ]}
          footnote="These panels stay empty until there is real work in them. Nothing on this dashboard is filled in with sample data."
        />
      </div>
    )
  }

  return (
    <div className="lm-screen flex flex-col gap-6 min-w-0">
      <div className="flex items-end gap-5 flex-wrap gap-y-2.5">
        <div>
          {/*
            * P3.2. This eyebrow read "Helwan Science Centre · Sunday 27 July",
            * both halves hardcoded. The school name is the same fabricated
            * affiliation P3.7 chunk b deleted from the teacher sidebar and
            * P3.10 chunk c from the student one — no field in any DTO supplies
            * a school name, so it is shown to every teacher regardless of where
            * they teach. The date was a literal, so it read "Sunday 27 July"
            * on every day of the year.
            *
            * The date is real now. The school name is simply gone rather than
            * replaced: there is nothing to replace it with, and inventing an
            * affiliation is the defect, not the formatting.
            */}
          <div className="font-mono text-2xs tracking-[0.11em] uppercase text-t3">
            {today}
          </div>
          <h1 className="text-display-lg mt-2">{greeting}.</h1>
          <div className="text-sm text-t2 mt-2 max-w-[62ch] text-pretty">
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
      <div className="bg-surface border border-border rounded-lg overflow-hidden max-w-[620px] w-full">
        <div className="px-5 pt-[18px] pb-[13px]">
          <div className="text-display-sm">Needs you</div>
          <div className="font-mono text-3xs tracking-[0.1em] uppercase text-t3 mt-[5px]">
            Flagged by trajectory, not by one bad day
          </div>
        </div>
        {atRisk.length === 0 ? (
          <div className="border-t border-border px-5 py-[15px] text-dense text-ok">
            No students flagged right now.
          </div>
        ) : (
          atRisk.map((r) => (
            <div
              key={r.name}
              className="border-t border-border px-5 py-[15px] flex gap-[13px] items-start"
            >
              <Avatar name={r.name} size="sm" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-[9px] flex-wrap gap-y-1">
                  <div className="text-dense-lg font-medium">{r.name}</div>
                  <div className="text-xs text-t2">Grade {r.grade}</div>
                  <div className="flex-1" />
                  {r.delta !== null ? (
                    <div
                      className={cn(
                        "font-mono text-xs",
                        r.delta < 0 ? "text-err" : r.delta > 0 ? "text-ok" : "text-t2",
                      )}
                    >
                      {r.delta > 0 ? "+" : ""}
                      {Math.round(r.delta)} pts
                    </div>
                  ) : null}
                </div>
                {r.weakTopic ? (
                  <div className="text-dense-sm text-t2 mt-[5px] leading-[1.45] text-pretty">
                    Weakest topic: {r.weakTopic}
                  </div>
                ) : null}
                {r.flags.length > 0 ? (
                  <div className="flex flex-col gap-[7px] mt-[9px]">
                    {r.flags.map((f) => (
                      <div
                        key={f.reason}
                        className="flex items-start gap-2 text-dense-sm text-t2 leading-[1.45]"
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
        <div className="text-dense text-ok -mt-2">
          Nothing needs your review right now — good news.
        </div>
      ) : null}

      {/* 3. Class summary cards */}
      <div>
        <div className="text-display-sm mb-3">Your classes</div>
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
                className="block bg-surface border border-border rounded-lg p-[18px] hover:bg-surface-2 transition-colors"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-display-xs">{c.label}</div>
                    <div className="font-mono text-2xs text-t3 mt-0.5">
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
                    <div className="font-mono text-3xs uppercase tracking-[0.08em] text-t3">
                      Average mark
                    </div>
                    <div className="text-display-sm mt-1">
                      {c.average != null ? `${Math.round(c.average)}%` : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="font-mono text-3xs uppercase tracking-[0.08em] text-t3">
                      Top weakness
                    </div>
                    <div className="text-dense mt-1 text-pretty">
                      {c.topWeakness ?? "Not enough data yet"}
                    </div>
                  </div>
                </div>
                <div className="text-xs text-t3 mt-3">
                  {c.lastActivityAt ? `Active ${relativeTime(c.lastActivityAt)}` : "No activity yet"}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* 4. Recent activity */}
      <div className="bg-surface border border-border rounded-lg overflow-hidden">
        <div className="px-5 pt-[18px] pb-[13px]">
          <div className="text-display-sm">Recent activity</div>
          <div className="font-mono text-3xs tracking-[0.1em] uppercase text-t3 mt-[5px]">
            Submissions across your classes
          </div>
        </div>
        {recentActivity.length === 0 ? (
          <div className="border-t border-border px-5 py-[15px] text-dense text-t2">
            No submissions yet.
          </div>
        ) : (
          recentActivity.map((a) => (
            <div
              key={`${a.studentId}-${a.subjectCode}-${a.recordedAt}`}
              className="border-t border-border px-5 py-[13px] flex items-center gap-3 flex-wrap gap-y-1.5"
            >
              <Avatar name={a.studentName} size="sm" />
              <div className="text-dense">{a.studentName}</div>
              <div className="font-mono text-xs text-t3">{a.subjectCode}</div>
              <div className="flex-1" />
              <div className="font-mono text-dense">{Math.round(a.percentage)}%</div>
              {a.grade ? (
                <GradeBadge grade={a.grade} size="inline" basis="achieved" />
              ) : (
                <span className="text-2xs text-t3 font-mono">{ORIGIN_LABEL[a.origin]}</span>
              )}
              <div className="text-2xs text-t3 w-[72px] text-end">{relativeTime(a.recordedAt)}</div>
            </div>
          ))
        )}
      </div>

      {/*
        * 5. Quick actions.
        *
        * P3.2: "Build a quiz" and "Post an announcement" were `disabled` with
        * a "Coming soon" chip and a `title` of "Coming in a later release".
        * Both features shipped. `/teacher/quizzes` is wired to
        * `GET /teacher/quizzes` and the full quiz-builder API, and
        * `/teacher/announcements` to `useAnnouncements()`; both are screens in
        * the sidebar this teacher can already open. So the dashboard was
        * telling them a feature does not exist while linking to it two feet to
        * the left, which is worse than a dead button: it is a reason not to
        * click a working one. Enabled and pointed at the real screens.
        */}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" onClick={() => navigate("/teacher/quizzes")}>
          Build a quiz
        </Button>
        <Button variant="secondary" onClick={() => navigate("/teacher/announcements")}>
          Post an announcement
        </Button>
        <Button variant="ink" onClick={() => navigate("/teacher/classes")}>
          Add a class
        </Button>
      </div>
    </div>
  )
}

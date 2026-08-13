import { useNavigate } from "react-router-dom"
import { Card } from "@/components/ui/card"
import { Meter } from "@/components/ui/primitives"
import { GradeBadge } from "@/components/ui/grade-badge"
import { ErrorState } from "@/components/ui/state-views"
import { GettingStarted } from "@/components/ui/getting-started"
import { greetingFor } from "@/lib/utils"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { vizBg } from "../components/colors"

/*
 * Overview (isOverview). Wired to `GET /student/overview` via `useOverview()`.
 * Greeting, subjects ledger, momentum sparkline + weakest threads. The mock's
 * "what to study next" / "this week" agenda / IG-calculator cards and the
 * hardcoded "Papers marked"/"Hours saved" stats + greeting body copy had no
 * backing DTO field and were removed rather than left as stale fabricated
 * content (see D1.6 finding M2).
 */
export function Overview() {
  const navigate = useNavigate()
  const { data, isPending, isError, error, refetch } = useOverview()

  if (isPending) {
    return (
      <div className="lm-screen flex flex-col gap-26px">
        <h1 className="sr-only">Overview</h1>
        <div role="status" className="text-sm text-t2">
          Loading overview…
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="lm-screen flex flex-col gap-26px">
        <h1 className="sr-only">Overview</h1>
        <ErrorState
          heading="Couldn't load your overview"
          body={error.message}
          action={{ label: "Try again", onClick: () => refetch() }}
        />
      </div>
    )
  }

  const { studentName, forecast, subjects, weakGlobal, momentum } = data

  // `studentName` is the authenticated user's id, not a display name (no
  // user-profile name store exists yet) — fall back to a plain greeting
  // rather than showing a raw id/UUID.
  const greetingName = studentName || "there"

  // This read "Good afternoon" unconditionally, at every hour of the day, so
  // a student revising at eleven at night was greeted as though it were two in
  // the afternoon. A small thing, but it is the first line on the first screen
  // and it was the one sentence on the page that was plainly untrue.
  const greeting = greetingFor(new Date().getHours())

  /*
   * First run (P3.2). A student who just onboarded has no results at all yet.
   *
   * This used to be a single centred `EmptyState` — "Correct your first paper
   * to see it here" and one button. That is a correct sentence and a poor
   * first screen: it says what is missing rather than what happens next, and
   * it gives no sense of how much setting-up is left. It is replaced by the
   * composed getting-started view Phase 3.2 asks for.
   *
   * What the steps may and may not claim is constrained by what this screen
   * can actually observe. `GET /student/overview` reports subjects derived
   * from corrected papers, so `subjects.length === 0` proves exactly one
   * thing: no paper has been marked yet. It does not tell us whether this
   * student has taken a placement test, and no endpoint on this screen does.
   *
   * So no step here is marked `done`. Marking the placement step complete
   * would be a guess, and marking it `now` alongside the paper step would give
   * a first-run reader two competing primary actions. It is `later`: true,
   * useful, and not a claim about what they have already done.
   */
  if (subjects.length === 0) {
    return (
      <div className="lm-screen flex flex-col gap-26px">
        <h1 className="text-display-lg text-t1">
          {greeting}, {greetingName}.
        </h1>
        <GettingStarted
          heading="Let's get your first paper marked"
          body="Lemely works from your own past papers. Mark one and this page fills in on its own."
          steps={[
            {
              title: "Correct your first paper",
              body: "Photograph or upload a paper you have already sat. Lemely finds the session and variant, pulls the official mark scheme, and marks it question by question.",
              status: "now",
              to: "/student/correct",
              actionLabel: "Correct a paper",
            },
            {
              title: "See where you stand",
              body: "Your predicted grade is measured against the real Cambridge grade boundaries for that paper, so it is a position rather than a percentage.",
              status: "later",
            },
            {
              title: "Get a study plan built from your own mistakes",
              body: "Every dropped mark is traced back to a topic. Those topics become practice questions, flashcards and a plan for the week that rewrites itself as you improve.",
              status: "later",
            },
          ]}
          footnote="Nothing here is filled in with sample data. This page stays empty until it has your own work to show."
        />
      </div>
    )
  }

  return (
    <div className="lm-screen flex flex-col gap-26px">
      <h1 className="text-display-lg text-t1">
        {greeting}, {greetingName}.
      </h1>

      <Card className="overflow-hidden">
        <div className="flex items-baseline gap-3 px-5 pt-18px pb-3.5">
          <div className="text-body-lg font-semibold">Subjects this session</div>
          <div className="flex-1" />
          <div className="text-xs text-t2">
            Forecast <span className="font-mono text-t1">{forecast}</span>
          </div>
        </div>
        {subjects.map((s) => (
          <button
            key={s.code}
            onClick={() => navigate(`/student/subject/${s.code}`)}
            className="flex flex-col gap-2 md:grid md:grid-subjects-row md:items-center md:gap-3.5 w-full text-left border-0 border-t border-border bg-transparent cursor-pointer px-5 py-3.5 transition-colors hover:bg-surface-2"
          >
            <div className="flex items-center gap-3 md:contents">
              <span className="font-mono text-xs text-t2">{s.code}</span>
              <span className="flex flex-col gap-1 flex-1 min-w-0 md:flex-none">
                <span className="text-sm font-medium">{s.name}</span>
                <span className="text-xs text-t2">{s.detail}</span>
              </span>
              <GradeBadge
                grade={s.grade}
                size="inline"
                basis="predicted"
                className="md:hidden"
              />
            </div>
            <span className="flex flex-col gap-5px">
              <Meter
                value={s.pct}
                label={`${s.name} mastery: ${s.pct}%`}
                fillClassName={vizBg(s.barColor)}
              />
              <span className="text-xs text-t2 font-mono">
                {s.pct}% - {s.papers} papers
              </span>
            </span>
            <span
              className={`text-xs font-mono ${s.trendUp ? "text-ok" : "text-err"}`}
            >
              {s.trend}
            </span>
            <GradeBadge
              grade={s.grade}
              size="inline"
              basis="predicted"
              className="hidden md:block md:ml-auto"
            />
          </button>
        ))}
      </Card>

      <div className="lm-cols grid grid-cols-2 gap-5 max-tablet:grid-cols-1">
        <Card className="px-5 py-18px">
          <div className="text-body-lg font-semibold">Momentum</div>
          <div className="text-xs text-t2 mb-4">
            Percentage per corrected paper, all subjects
          </div>
          <svg
            viewBox="0 0 300 88"
            className="w-full h-22 overflow-visible"
            aria-hidden="true"
          >
            <path d={momentum.area} fill="var(--accent-subtle)" />
            <path
              d={momentum.path}
              fill="none"
              stroke="var(--accent)"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <circle
              cx={momentum.lastX}
              cy={momentum.lastY}
              r={3.6}
              fill="var(--accent)"
            />
          </svg>
          <div className="flex justify-between text-2xs text-t3 font-mono mt-1.5">
            {momentum.labels.map((l) => (
              <span key={l}>{l}</span>
            ))}
          </div>
        </Card>

        <Card className="px-5 py-18px">
          <div className="text-body-lg font-semibold">Weakest threads</div>
          <div className="text-xs text-t2 mb-4">
            Accuracy by topic, all subjects
          </div>
          <div className="flex flex-col gap-13px">
            {weakGlobal.map((w) => (
              <div key={w.topic} className="flex flex-col gap-5px">
                <div className="flex justify-between text-sm">
                  <span>{w.topic}</span>
                  <span className="font-mono text-t2">{w.acc}</span>
                </div>
                <Meter
                  value={w.width}
                  label={`${w.topic} accuracy: ${w.acc}`}
                  fillClassName={vizBg(w.color)}
                />
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}

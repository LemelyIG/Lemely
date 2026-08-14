import { Link, useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { ListSkeleton, PageHeaderSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import { ProgressBar } from "@/components/ui/progress-bar"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import {
  useCompleteStudyPlanSession,
  useCurrentStudyPlan,
  useRebuildStudyPlan,
} from "@/lib/hooks/useStudyPlanApi"
import type { StudyPlanSessionDTO, StudyPlanWeekDTO } from "@/lib/studyPlanTypes"
import { SUPPORTED_SUBJECTS } from "@/portals/student/screens/onboarding/onboardingData"
import {
  activityLabel,
  formatDayHeading,
  formatDuration,
  groupSessionsByDay,
  planUnavailableMessage,
  studyPlanView,
  weekProgress,
} from "./studyPlanData"

/*
 * S-24 · Study plan, week view. Wired to the *persisted* study-plan surface
 * (`/api/student/study-plan`, P4.7 chunk C). The legacy stateless
 * `/api/student/plan` pair the previous version of this screen called was
 * deleted in P4.10 chunk D (D4.22).
 *
 * The screen's job is to keep D4.13's three wire states three states on the
 * glass — see `studyPlanView`. Two spec affordances are deliberately absent
 * rather than faked:
 *
 *   - **Reschedule (drag on desktop, move on mobile).** The router has three
 *     routes and none of them can move a session. A control that cannot
 *     persist its effect is worse than no control.
 *   - **XP on completion.** `completedAt` is Phase 5's seam and nothing more
 *     (D4.17 made the identical call for S-23). No number is put on the
 *     button.
 */

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */

const REBUILD_LABEL = "Rebuild this week's plan"

/** What the planner actually reads, stated once. This is a true description of
 * the algorithm (`StudyPlanService.generate` takes exactly these three
 * signals), not a per-student claim about which one drove any given session —
 * that is not recorded anywhere and must not be implied here. */
function PlanBasis() {
  return (
    <Card>
      <CardBody className="flex flex-col gap-1.5">
        <h2 className="text-display-sm text-ink">What this plan is based on</h2>
        <p className="lm-prose text-body-md text-ink-muted">
          Three things, weighted: topics you have lost marks on, your placement test result, and
          the confidence ratings you gave during onboarding. Whichever of those you have is what
          gets used, and a missing one is left out rather than guessed at.
        </p>
      </CardBody>
    </Card>
  )
}

function WeekHeader({
  plan,
  subjectName,
  onRebuild,
  rebuilding,
}: {
  plan: StudyPlanWeekDTO
  subjectName: string
  onRebuild: () => void
  rebuilding: boolean
}) {
  const progress = weekProgress(plan)
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-display-lg text-ink">Your {subjectName} week</h1>
          <p className="text-body-md text-ink-muted">
            Week of {formatDayHeading(plan.weekStart)}
          </p>
        </div>
        <div className="flex-1" />
        <Button variant="secondary" size="md" onClick={onRebuild} disabled={rebuilding}>
          {rebuilding ? "Rebuilding…" : REBUILD_LABEL}
        </Button>
      </div>

      <Card>
        <CardBody className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
            <span className="text-body-lg text-ink">
              <span className="text-data-md text-ink">{progress.completedCount}</span> of{" "}
              <span className="text-data-md text-ink">{progress.sessionCount}</span> session
              {progress.sessionCount === 1 ? "" : "s"} done
            </span>
            {/* Planned and stated are two different facts and stay two
                numbers. The scheduler caps a session at 90 minutes and can
                run out of topics worth scheduling, so planned time is
                routinely below the time the student said they had — showing
                only the stated figure would report time as planned that
                nothing was ever scheduled into. */}
            {/* Prose in the reading face with the two figures in the data
                face, rather than the whole sentence in mono. §4 gives the data
                face "scores, grades, marks, XP, timers" — figures, not the
                sentence around them — and a full line of Geist Mono read as a
                code string sitting inside a paragraph. */}
            <span className="text-body-sm text-ink-muted">
              <span className="text-data-sm text-ink-muted">
                {formatDuration(progress.plannedMinutes)}
              </span>{" "}
              planned of the{" "}
              <span className="text-data-sm text-ink-muted">
                {formatDuration(progress.statedMinutes)}
              </span>{" "}
              you said you had
            </span>
          </div>
          {/* C-24 ProgressBar. The bar this replaced was hand-rolled and drove
              its fill with `transition-[width]`, which §9.2 forbids outright
              (transform and opacity only) — a layout-animating property on the
              one element that changes every time a session is ticked off.

              It also carried a labelling defect. `percentComplete` is
              completed MINUTES over planned minutes, while the line directly
              above it counts SESSIONS, so a student who had finished two short
              sessions of four saw "2 of 4 sessions done" beside a bar sitting
              at 25%, with nothing on screen explaining the disagreement. The
              bar now states its own denominator in its own label, so the two
              numbers no longer look like one number rendered twice. */}
          <ProgressBar
            value={progress.percentComplete}
            label={`${formatDuration(progress.completedMinutes)} of ${formatDuration(progress.plannedMinutes)} planned study time done`}
          />
          {progress.fullyComplete ? (
            <p className="text-body-md text-ok">
              Every session this week is done. Nothing left to do here.
            </p>
          ) : null}
        </CardBody>
      </Card>
    </div>
  )
}

function SessionRow({
  session,
  subjectCode,
  onComplete,
  completing,
}: {
  session: StudyPlanSessionDTO
  subjectCode: string
  onComplete: (sessionId: string) => void
  completing: boolean
}) {
  const done = session.completedAt !== null
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-rule px-5 py-3.5 first:border-t-0">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {/* Opts out of §6.1's two-line-clickable rule: the label is a syllabus
            topic name ("2.1 Thermal physics"), which is content, not a control
            label. At 320px it wraps; truncating a topic so a student cannot
            tell which session they are opening would be the worse trade. See
            scripts/adapt_audit.mjs. */}
        <Link
          to={`/student/plan/${subjectCode}/session/${session.id}`}
          data-wraps-content-title
          className="text-body-md font-medium text-ink no-underline hover:underline focus-visible:underline pointer-coarse:block pointer-coarse:py-[11px]"
        >
          {session.topic}
        </Link>
        <span className="text-body-sm text-ink-muted">
          {activityLabel(session.activityType)} · {formatDuration(session.durationMinutes)}
        </span>
      </div>
      {done ? (
        // A completed session states the fact and stops. No XP, no points —
        // `completedAt` is P5's seam (see the module docstring).
        <span className="text-body-sm text-ok">Completed</span>
      ) : (
        <Button
          variant="secondary"
          size="sm"
          disabled={completing}
          onClick={() => onComplete(session.id)}
        >
          {completing ? "Saving…" : "Mark complete"}
        </Button>
      )}
    </div>
  )
}

export function StudyPlanWeek() {
  const navigate = useNavigate()
  const { subjectCode = "" } = useParams<{ subjectCode: string }>()
  const subjectName = SUPPORTED_SUBJECTS.find((s) => s.code === subjectCode)?.name ?? subjectCode

  const planQuery = useCurrentStudyPlan(subjectCode)
  const rebuild = useRebuildStudyPlan()
  const complete = useCompleteStudyPlanSession()

  const heading = `Your ${subjectName} week`
  const onRebuild = () => rebuild.mutate({ subjectCode })

  if (planQuery.isPending) {
    return (
      <div className="lm-screen lm-read flex flex-col gap-6">
        <h1 className="sr-only">{heading}</h1>
        <PageHeaderSkeleton />
        <PanelSkeleton />
        <ListSkeleton rows={4} />
      </div>
    )
  }

  // A query error here is a *real* failure. "No plan yet" comes back as a
  // successful `{generated: false}` and never as an error, so this branch must
  // not be shared with the empty state (see `useCurrentStudyPlan`).
  if (planQuery.isError || !planQuery.data) {
    return (
      <>
        <h1 className="sr-only">{heading}</h1>
        <ErrorState
          heading="Couldn't load your study plan"
          body={planQuery.error?.message}
          action={{ label: "Try again", onClick: () => void planQuery.refetch() }}
          className="lm-screen"
        />
      </>
    )
  }

  const view = studyPlanView(planQuery.data)

  const rebuildError = rebuild.isError ? (
    <p className="text-body-md text-err">Couldn't rebuild your plan: {rebuild.error.message}</p>
  ) : null
  const completeError = complete.isError ? (
    <p className="text-body-md text-err">
      Couldn't mark that session complete: {complete.error.message}
    </p>
  ) : null

  if (view.kind === "notGenerated") {
    return (
      <>
        <h1 className="sr-only">{heading}</h1>
        <EmptyState
          marginalia="A blank week, for now"
          heading="No plan for this week yet"
          body={`You don't have a ${subjectName} plan for this week. Build one and it will lay out concrete sessions across the days you have left.`}
          action={{
            label: rebuild.isPending ? "Building…" : "Build this week's plan",
            onClick: onRebuild,
          }}
          secondaryAction={{
            label: "Take the placement test",
            onClick: () => navigate(`/student/placement/${subjectCode}`),
          }}
          className="lm-screen"
        />
        {rebuildError ? <div className="lm-screen pt-0">{rebuildError}</div> : null}
      </>
    )
  }

  if (view.kind === "refused") {
    const message = planUnavailableMessage(view.reason)
    return (
      <div className="lm-screen lm-read flex flex-col gap-6">
        <h1 className="text-display-lg text-ink">{heading}</h1>
        <EmptyState
          marginalia="Not enough to go on yet"
          heading={message.heading}
          body={message.body}
          action={{
            label: "Take the placement test",
            onClick: () => navigate(`/student/placement/${subjectCode}`),
          }}
          secondaryAction={{
            label: rebuild.isPending ? "Rebuilding…" : REBUILD_LABEL,
            onClick: onRebuild,
          }}
        />
        {rebuildError}
      </div>
    )
  }

  const plan = view.plan
  const days = groupSessionsByDay(plan.sessions)

  return (
    <div className="lm-screen lm-read flex flex-col gap-6">
      <WeekHeader
        plan={plan}
        subjectName={subjectName}
        onRebuild={onRebuild}
        rebuilding={rebuild.isPending}
      />
      {rebuildError}
      {completeError}
      <PlanBasis />

      {days.length === 0 ? (
        // Distinct from both branches above: the planner *did* have something
        // to go on and produced a week with nothing in it. Saying "no plan
        // yet" here would be false, and saying "not enough to plan from"
        // would be false too.
        <EmptyState
          marginalia="Nothing pencilled in"
          heading="Nothing scheduled this week"
          body="The planner had something to go on but found nothing worth scheduling for this subject this week. Correct a paper or run some practice and rebuild to give it more to work with."
          action={{ label: "Practice", onClick: () => navigate(`/student/practice/${subjectCode}`) }}
        />
      ) : (
        <div className="flex flex-col gap-5">
          {days.map((day) => (
            <section key={day.date} className="flex flex-col gap-2">
              <h2 className="text-display-sm text-ink">{formatDayHeading(day.date)}</h2>
              <Card className="overflow-hidden">
                {day.sessions.map((session) => (
                  <SessionRow
                    key={session.id}
                    session={session}
                    subjectCode={subjectCode}
                    onComplete={(sessionId) => complete.mutate({ sessionId, subjectCode })}
                    completing={complete.isPending && complete.variables?.sessionId === session.id}
                  />
                ))}
              </Card>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

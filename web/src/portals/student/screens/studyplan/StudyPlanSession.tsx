import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { usePracticeTopics } from "@/lib/hooks/usePracticeApi"
import {
  useCompleteStudyPlanSession,
  useCurrentStudyPlan,
} from "@/lib/hooks/useStudyPlanApi"
import { SUPPORTED_SUBJECTS } from "@/portals/student/screens/onboarding/onboardingData"
import { studentActionFailureMessage, studentLoadFailureMessage } from "@/lib/studentOutcome"
import {
  activityLabel,
  formatDayHeading,
  formatDuration,
  locateSession,
  planUnavailableMessage,
  rationaleCopy,
  sessionRationale,
  sessionStartAction,
} from "./studyPlanData"

/*
 * S-25 · Study-plan session detail.
 *
 * Three things about this screen are decisions, not accidents:
 *
 *   1. **It reads the week, not the session.** There is no `GET /sessions/{id}`
 *      route, so the session is located inside `useCurrentStudyPlan` (see
 *      `locateSession`). A session id that is not in the current week is a
 *      real state — regeneration supersedes rather than mutates — and it is
 *      rendered as "your plan moved on", never as "not found".
 *   2. **The "why" is the one provable join and nothing more.** `focus` is a
 *      restatement of activity + topic and is never rendered as a reason; the
 *      only defensible statement is whether the topic is one of the student's
 *      recorded weak topics, which is read from the query whose SQL is
 *      byte-identical to the planner's own. When that query has not answered,
 *      the screen says it does not know.
 *   3. **No XP on completion** (P5's seam is `completedAt`) and **no start
 *      button for a `review` session** — this product has no revision surface,
 *      so the button would be dead.
 */

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */

/** One fact per row. `numeric` puts the value on the data face (§4): a planned
 * duration is a figure, a topic name is prose, and rendering both in the same
 * family is what made this table read as undifferentiated. */
function DetailRow({
  label,
  value,
  numeric = false,
}: {
  label: string
  value: string
  numeric?: boolean
}) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-t border-rule px-5 py-3 first:border-t-0">
      <span className="text-body-sm text-ink-muted">{label}</span>
      <span className={numeric ? "text-data-md text-ink" : "text-body-md text-ink"}>{value}</span>
    </div>
  )
}

export function StudyPlanSession() {
  const navigate = useNavigate()
  const { subjectCode = "", sessionId = "" } = useParams<{
    subjectCode: string
    sessionId: string
  }>()
  const subjectName = SUPPORTED_SUBJECTS.find((s) => s.code === subjectCode)?.name ?? subjectCode

  const planQuery = useCurrentStudyPlan(subjectCode)
  const topicsQuery = usePracticeTopics(subjectCode)
  const complete = useCompleteStudyPlanSession()

  const heading = "Study session"
  const backToWeek = () => navigate(`/student/plan/${subjectCode}`)

  if (planQuery.isPending) {
    return (
      <div className="lm-screen lm-read flex flex-col gap-6">
        <h1 className="sr-only">{heading}</h1>
        <PageHeaderSkeleton />
        <ListSkeleton rows={5} />
      </div>
    )
  }

  // As on S-24: a query error is a real failure. "No plan" and "session not in
  // this week" both arrive as successful responses and are handled below.
  if (planQuery.isError || !planQuery.data) {
    return (
      <>
        <h1 className="sr-only">{heading}</h1>
        <ErrorState
          heading="Couldn't load this session"
          body={studentLoadFailureMessage(planQuery.error)}
          action={{ label: "Try again", onClick: () => void planQuery.refetch() }}
          className="lm-screen"
        />
      </>
    )
  }

  const located = locateSession(planQuery.data, sessionId)

  if (located.kind === "noCurrentPlan") {
    // The week itself is not there to hold this session. Keep S-24's own
    // distinction rather than flattening both into one message.
    const body =
      located.view.kind === "refused"
        ? planUnavailableMessage(located.view.reason).body
        : `You don't have a ${subjectName} plan for this week, so this session isn't part of anything current. Plans are rebuilt weekly and a rebuild supersedes the previous week rather than editing it.`
    return (
      <>
        <h1 className="sr-only">{heading}</h1>
        <EmptyState
          marginalia="A page that turned"
          heading="This session isn't in your current plan"
          body={body}
          action={{ label: "Go to your week", onClick: backToWeek }}
          className="lm-screen"
        />
      </>
    )
  }

  if (located.kind === "notInCurrentWeek") {
    return (
      <>
        <h1 className="sr-only">{heading}</h1>
        <EmptyState
          // Not "not found": the session existed and may well still exist on a
          // superseded week. Saying it is missing would be a stronger claim
          // than anything this screen can check.
          marginalia="A page that turned"
          heading="This session isn't in your current plan"
          body={`Your ${subjectName} plan has been rebuilt since this link was made, and rebuilding supersedes the previous week rather than editing it. This week's sessions are on your plan.`}
          action={{ label: "Go to your week", onClick: backToWeek }}
          className="lm-screen"
        />
      </>
    )
  }

  const session = located.session
  const done = session.completedAt !== null
  const rationale = sessionRationale(
    session.topic,
    topicsQuery.isSuccess ? topicsQuery.data.weakTopics : undefined,
  )
  const why = rationaleCopy(rationale, session.topic)
  const start = sessionStartAction(session.activityType, subjectCode)

  return (
    <div className="lm-screen lm-read flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-display-lg text-ink">{session.topic}</h1>
        <p className="text-body-md text-ink-muted">
          {activityLabel(session.activityType)} · {formatDuration(session.durationMinutes)} ·{" "}
          {formatDayHeading(session.date)}
        </p>
      </div>

      <Card className="overflow-hidden">
        <DetailRow label="Topic" value={session.topic} />
        <DetailRow label="Activity" value={activityLabel(session.activityType)} />
        <DetailRow label="Planned time" value={formatDuration(session.durationMinutes)} numeric />
        <DetailRow label="Scheduled for" value={formatDayHeading(session.date)} />
        <DetailRow label="Status" value={done ? "Completed" : "Not done yet"} />
      </Card>

      <Card>
        <CardBody className="flex flex-col gap-1.5">
          <h2 className="text-display-sm text-ink">{why.heading}</h2>
          <p className="lm-prose text-body-md text-ink-muted">{why.body}</p>
        </CardBody>
      </Card>

      {/* P6.2. This appended `complete.error.message` to the sentence, so a
          failed tap read "Couldn't mark this session complete: 500 Internal
          Server Error" — or, on the phone this is used on, "Failed to fetch".
          The save helper, not the load one: the student's question after a
          failed write is whether it stuck, and none of its sentences claims it
          did. */}
      {complete.isError ? (
        <p className="text-body-md text-err">
          {studentActionFailureMessage(complete.error, "mark this session as done")}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3">
        {/* No start control for `review`: nothing in this product renders
            revision material, so the button would go nowhere. */}
        {start ? (
          <Button variant="accent" size="md" onClick={() => navigate(start.path)}>
            {start.label}
          </Button>
        ) : null}
        {done ? (
          // States the fact and stops — no XP, no points (P5's seam).
          <span className="self-center text-body-sm text-ok">Marked complete</span>
        ) : (
          <Button
            variant="secondary"
            size="md"
            disabled={complete.isPending}
            onClick={() => complete.mutate({ sessionId: session.id, subjectCode })}
          >
            {complete.isPending ? "Saving…" : "Mark complete"}
          </Button>
        )}
        <Button variant="ghost" size="md" onClick={backToWeek}>
          Back to your week
        </Button>
      </div>
    </div>
  )
}

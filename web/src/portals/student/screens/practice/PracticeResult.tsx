import { useLocation, useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { CountUp } from "@/components/ui/celebration"
import { Card, CardBody } from "@/components/ui/card"
import { ConfidenceIndicatorSummary } from "@/components/ui/confidence-indicator"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { ProgressBar } from "@/components/ui/progress-bar"
import { QuestionRow } from "@/components/ui/question-row"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { formatQuestionTopic } from "@/components/quiz/quizTakerData"
import { usePracticeResult } from "@/lib/hooks/usePracticeApi"
import { useSubjectName } from "@/lib/hooks/useReferenceApi"
import { confidenceBandTier, practiceMarkState, practiceResultView } from "./practiceData"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */

/*
 * S-21 · Practice set finish summary. The whole render decision — not
 * submitted / submitted-and-marking / marked — is made once, in
 * `practiceResultView` (`practiceData.ts`, unit-tested directly), not
 * re-derived here: this screen only switches on `view.kind`. `marked:false`
 * never carries a marks field the screen could coerce into a rendered `0`
 * (mirrors `PlacementResult`'s identical discipline). Every awarded mark on
 * the "marked" branch carries its own confidence via `QuestionRow`'s C-4
 * chip — no new confidence display is built here.
 *
 * P4.3 (Study Notebook). Two things beyond styling:
 *
 *   1. **The marking wait was a bare spinning glyph.** DESIGN.md §12 allows a
 *      spinner only for "an indeterminate action under ~1s inside a button",
 *      and this is a page-level wait on a server-side marking job. It is now
 *      C-24 `ProgressBar` in its `indeterminate` mode, whose own docstring
 *      names this exact case. The correction flow (surface 2) already handles
 *      its marking wait properly; this is the same wait on the same product
 *      rendered two different ways, which is P4.2's lesson 2 — a defect fixed
 *      on one flow is still live on another.
 *   2. **The mark total was prose.** "{awarded} of {max} marks" was
 *      `text-body-md`, i.e. Geist, where §4 gives the data face "all scores,
 *      grades, marks". This is the same finding as D4.2 item 3 on the paper
 *      result, one screen along: the number a student opens this page to read
 *      was set in the reading face.
 */
/**
 * True when `PracticeSet` navigated here on submit, rather than the student
 * opening this result again from somewhere else.
 *
 * Narrowed rather than cast: `location.state` is `unknown` and arrives from the
 * history entry, so it survives a reload and can be anything at all.
 */
function isJustSubmitted(state: unknown): boolean {
  return (
    typeof state === "object" &&
    state !== null &&
    (state as { justSubmitted?: unknown }).justSubmitted === true
  )
}

export function PracticeResult() {
  const navigate = useNavigate()
  const location = useLocation()
  const justSubmitted = isJustSubmitted(location.state)
  const { assignmentId = "" } = useParams<{ assignmentId: string }>()
  const query = usePracticeResult(assignmentId)
  const subjectName = useSubjectName(query.data?.subjectCode ?? "")

  return (
    <div className="lm-screen lm-read flex flex-col gap-6">
      <QueryState
        query={query}
        srHeading="Practice set result"
        skeleton={
          <>
            <PageHeaderSkeleton />
            <ListSkeleton rows={5} />
          </>
        }
        /* `usePracticeResult` disables itself (`enabled: !!assignmentId`)
           rather than fetching an empty id — reachable only from a malformed
           link missing its assignment segment. */
        idle={
          <EmptyState
            marginalia="Nothing to show"
            heading="No practice set selected"
            body="This link is missing which practice set to show. Go back and open your result from the dashboard."
            action={{ label: "Back to dashboard", onClick: () => navigate("/student") }}
          />
        }
        error={{
          heading: "Couldn't load this practice set",
          body: studentLoadFailureMessage,
        }}
      >
        {(data) => {
          const view = practiceResultView(data)

          if (view.kind === "not_submitted") {
            return (
              <EmptyState
                marginalia="Still open on the desk"
                heading="This practice set hasn't been submitted yet"
                body={`Finish and submit your ${subjectName} practice set to see how you did.`}
                action={{
                  label: "Continue the set",
                  onClick: () => navigate(`/student/practice/set/${data.assignmentId}`),
                }}
              />
            )
          }

          if (view.kind === "marking") {
            return (
              <div className="flex flex-col gap-5 py-12">
                <h1 className="text-display-lg text-ink">
                  Marking your {subjectName} practice set
                </h1>
                <p className="lm-prose text-body-lg text-ink-muted">
                  This usually only takes a moment. The page updates on its own, so there's no
                  need to refresh.
                </p>
                <ProgressBar indeterminate ariaLabel="Marking your practice set" />
                <div>
                  <Button variant="ghost" onClick={() => navigate("/student")}>
                    Come back to this later
                  </Button>
                </div>
              </div>
            )
          }

          const { awardedMarks, maximumMarks, questions } = view
          const summary = questions.reduce(
            (acc, q) => {
              const tier = confidenceBandTier(q.confidenceBand)
              if (tier === "confident") acc.confident += 1
              else if (tier === "uncertain") acc.uncertain += 1
              else acc.needsReview += 1
              return acc
            },
            { confident: 0, uncertain: 0, needsReview: 0 },
          )

          return (
            <>
              <div className="flex flex-col gap-3">
                <h1 className="text-display-lg text-ink">Your {subjectName} practice set</h1>
                {/* The data face, per §4 and §4.2's `data-lg` rung ("the big
                    number: a score"). This is the figure the screen exists to
                    deliver. */}
                <p className="flex items-baseline gap-2">
                  <span className="text-data-lg text-ink">
                    {/* §9.3's result reveal, on the same rule the paper
                        result uses: the mark counts up only when it arrived
                        while the student was waiting for it. Opening this
                        set again later shows the number at once, because by
                        then it is simply true. No flourish at any mark — see
                        `MarkDisplay`'s `reveal` for why the product has no
                        honest basis for deciding a mark deserves confetti. */}
                    {justSubmitted ? <CountUp value={awardedMarks} from={0} /> : awardedMarks}/
                    {maximumMarks}
                  </span>
                  <span className="text-body-lg text-ink-muted">
                    mark{maximumMarks === 1 ? "" : "s"}
                  </span>
                </p>
              </div>

              <ConfidenceIndicatorSummary
                confident={summary.confident}
                uncertain={summary.uncertain}
                needsReview={summary.needsReview}
              />

              <Card>
                <CardBody className="flex flex-col p-0">
                  {questions.length === 0 ? (
                    <p className="p-5 text-body-sm text-ink-faint">No questions in this set.</p>
                  ) : (
                    <div className="px-5">
                      {questions.map((q) => (
                        <QuestionRow
                          key={q.questionRef}
                          number={q.position}
                          awarded={q.awardedMarks}
                          available={q.totalMarks}
                          state={practiceMarkState(q.awardedMarks, q.totalMarks)}
                          confidence={confidenceBandTier(q.confidenceBand)}
                          topic={formatQuestionTopic(q.topic)}
                        />
                      ))}
                    </div>
                  )}
                </CardBody>
              </Card>

              <div className="flex flex-wrap gap-3">
                {/* Subject-scoped since P4.10: the study plan is per-subject,
                    and `data.subjectCode` is this set's real subject — never
                    a default. */}
                <Button
                  variant="accent"
                  size="lg"
                  onClick={() => navigate(`/student/plan/${data.subjectCode}`)}
                >
                  See your study plan
                </Button>
                <Button variant="ghost" size="lg" onClick={() => navigate("/student")}>
                  Back to dashboard
                </Button>
              </div>
            </>
          )
        }}
      </QueryState>
    </div>
  )
}

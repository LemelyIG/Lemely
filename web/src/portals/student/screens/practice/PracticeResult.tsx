import { CircleNotch } from "@phosphor-icons/react"
import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { ConfidenceIndicatorSummary } from "@/components/ui/confidence-indicator"
import { QuestionRow } from "@/components/ui/question-row"
import { ErrorState } from "@/components/ui/state-views"
import { formatQuestionTopic } from "@/components/quiz/quizTakerData"
import { usePracticeResult } from "@/lib/hooks/usePracticeApi"
import { SUPPORTED_SUBJECTS } from "@/portals/student/screens/onboarding/onboardingData"
import { confidenceBandTier, practiceMarkState, practiceResultView } from "./practiceData"

/*
 * S-21 · Practice set finish summary. The whole render decision — not
 * submitted / submitted-and-marking / marked — is made once, in
 * `practiceResultView` (`practiceData.ts`, unit-tested directly), not
 * re-derived here: this screen only switches on `view.kind`. `marked:false`
 * never carries a marks field the screen could coerce into a rendered `0`
 * (mirrors `PlacementResult`'s identical discipline). Every awarded mark on
 * the "marked" branch carries its own confidence via `QuestionRow`'s C-4
 * chip — no new confidence display is built here.
 */
export function PracticeResult() {
  const navigate = useNavigate()
  const { assignmentId = "" } = useParams<{ assignmentId: string }>()
  const { data, isPending, isError, error, refetch } = usePracticeResult(assignmentId)

  if (isPending) {
    return (
      <div className="lm-screen text-body-md text-t2">
        <h1 className="sr-only">Practice set result</h1>
        Loading your practice set…
      </div>
    )
  }

  if (isError || !data) {
    return (
      <>
        <h1 className="sr-only">Practice set result</h1>
        <ErrorState
          heading="Couldn't load this practice set"
          body={error?.message}
          action={{ label: "Try again", onClick: () => void refetch() }}
          className="lm-screen"
        />
      </>
    )
  }

  const subjectName = SUPPORTED_SUBJECTS.find((s) => s.code === data.subjectCode)?.name ?? data.subjectCode
  const view = practiceResultView(data)

  if (view.kind === "not_submitted") {
    return (
      <div className="lm-screen mx-auto flex max-w-[560px] flex-col items-center gap-4 py-16 text-center">
        <h1 className="text-body-lg font-medium text-t1 m-0">This practice set hasn't been submitted yet</h1>
        <p className="text-body-md text-t2">
          Finish and submit your {subjectName} practice set to see how you did.
        </p>
        <Button variant="accent" onClick={() => navigate(`/student/practice/set/${data.assignmentId}`)}>
          Continue the set
        </Button>
      </div>
    )
  }

  if (view.kind === "marking") {
    return (
      <div className="lm-screen mx-auto flex max-w-[560px] flex-col items-center gap-4 py-16 text-center">
        <CircleNotch size={28} className="animate-spin text-accent" aria-hidden />
        <h1 className="text-body-lg font-medium text-t1 m-0">Marking your {subjectName} practice set</h1>
        <p className="text-body-md text-t2">
          This usually only takes a moment. This page will update on its own — no need to refresh.
        </p>
        <Button variant="ghost" onClick={() => navigate("/student")}>
          Come back to this later
        </Button>
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
    <div className="lm-screen mx-auto flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-serif text-display-md leading-display text-t1 m-0">
          Your {subjectName} practice set
        </h1>
        <p className="text-body-md text-t2">
          {awardedMarks} of {maximumMarks} mark{maximumMarks === 1 ? "" : "s"}.
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
            <p className="p-5 text-dense-sm text-t3">No questions in this set.</p>
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
        {/* Subject-scoped since P4.10: the study plan is per-subject, and
            `data.subjectCode` is this set's real subject — never a default. */}
        <Button variant="accent" size="lg" onClick={() => navigate(`/student/plan/${data.subjectCode}`)}>
          See your study plan
        </Button>
        <Button variant="ghost" size="lg" onClick={() => navigate("/student")}>
          Back to dashboard
        </Button>
      </div>
    </div>
  )
}

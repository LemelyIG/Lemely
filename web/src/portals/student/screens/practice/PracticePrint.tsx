import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { ErrorState } from "@/components/ui/state-views"
import { formatQuestionTopic } from "@/components/quiz/quizTakerData"
import { usePracticeExport } from "@/lib/hooks/usePracticeApi"

/*
 * S-21 print/export view — the natural use of `GET
 * /api/student/practice/{assignmentId}/export`'s answer-free payload
 * (`PracticeExportDTO`): a plain worksheet a student can do on paper. No
 * model answer, mark scheme, or MCQ answer field exists anywhere on this
 * DTO by construction (D3.8) — nothing here could reveal one even by
 * accident. There is no route to attach a photographed answer back to this
 * quiz (`SaveAnswerRequest` is text-only, `placementTypes.ts`), so this
 * screen only offers the print affordance, not a "submit your photo" one —
 * a student who does this on paper types their answer back into the
 * on-screen set (S-21 working view) afterwards, the same as any other
 * text-only answer path.
 */
export function PracticePrint() {
  const navigate = useNavigate()
  const { assignmentId = "" } = useParams<{ assignmentId: string }>()
  const { data, isPending, isError, error, refetch } = usePracticeExport(assignmentId)

  if (isPending) {
    return (
      <div className="lm-screen text-body-md text-t2">
        <h1 className="sr-only">Practice set — print</h1>
        Loading your practice set…
      </div>
    )
  }

  if (isError || !data) {
    return (
      <>
        <h1 className="sr-only">Practice set — print</h1>
        <ErrorState
          heading="Couldn't load this practice set"
          body={error?.message}
          action={{ label: "Try again", onClick: () => void refetch() }}
          className="lm-screen"
        />
      </>
    )
  }

  return (
    <div className="lm-screen mx-auto flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-serif text-display-md leading-display text-t1 m-0">{data.title}</h1>
        <div className="flex flex-wrap gap-3 print:hidden">
          <Button variant="accent" onClick={() => window.print()}>
            Print
          </Button>
          <Button variant="ghost" onClick={() => navigate(`/student/practice/set/${assignmentId}`)}>
            Answer on screen instead
          </Button>
        </div>
      </div>

      <Card className="print:border-0">
        <CardBody className="flex flex-col gap-6">
          {data.questions.map((q) => (
            <div key={q.questionRef} className="flex flex-col gap-2 border-b border-border pb-5 last:border-b-0">
              <div className="flex items-center gap-3 text-dense-sm text-t3">
                <span className="font-mono">Q{q.position}</span>
                <span>{q.totalMarks} mark{q.totalMarks === 1 ? "" : "s"}</span>
                <span>{formatQuestionTopic(q.topic)}</span>
              </div>
              <p className="whitespace-pre-line text-body-md text-t1">{q.prompt}</p>
              {q.mcqOptions ? (
                <ul className="flex flex-col gap-1 pl-4 text-body-md text-t1">
                  {q.mcqOptions.map((option) => (
                    <li key={option}>{option}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  )
}

import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { formatQuestionTopic } from "@/components/quiz/quizTakerData"
import { usePracticeExport } from "@/lib/hooks/usePracticeApi"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"

/* Hallmark · pre-emit critique: P4 H4 E5 S4 R4 V4 */

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
 *
 * P4.3 (Study Notebook). Three things beyond styling:
 *
 *   1. **`pl-4` on the MCQ option list** — a hardcoded physical-left padding
 *      on the one screen whose entire content is indented question text. P3.4's
 *      RTL rule makes this `ps-4`.
 *   2. **An export with no questions rendered as an empty bordered box.** The
 *      map over `data.questions` had no zero case, so a set that exported
 *      nothing produced a card containing nothing, with a Print button above
 *      it that would have printed a blank sheet.
 *   3. **The print stylesheet was one `print:hidden`.** This screen's whole
 *      purpose is the printed artefact, so it is the one screen in the product
 *      where print is the primary medium rather than an afterthought: the
 *      texture layer is already excluded from print globally (§8), and the
 *      answer space students actually need is now reserved per question.
 */
export function PracticePrint() {
  const navigate = useNavigate()
  const { assignmentId = "" } = useParams<{ assignmentId: string }>()
  const { data, isPending, isError, error, refetch } = usePracticeExport(assignmentId)

  if (isPending) {
    return (
      <div className="lm-screen lm-read flex flex-col gap-6">
        <h1 className="sr-only">Print your practice set</h1>
        <PageHeaderSkeleton />
        <ListSkeleton rows={5} />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <>
        <h1 className="sr-only">Print your practice set</h1>
        <ErrorState
          heading="Couldn't load this practice set"
          body={studentLoadFailureMessage(error)}
          action={{ label: "Try again", onClick: () => void refetch() }}
          className="lm-screen"
        />
      </>
    )
  }

  if (data.questions.length === 0) {
    return (
      <>
        <h1 className="sr-only">Print your practice set</h1>
        <EmptyState
          marginalia="A blank sheet"
          heading="There's nothing in this set to print"
          body="This practice set exported without any questions, so there is no worksheet to put on paper."
          action={{
            label: "Build another set",
            onClick: () => navigate("/student"),
          }}
          className="lm-screen"
        />
      </>
    )
  }

  return (
    <div className="lm-screen lm-read flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-display-lg text-ink">{data.title}</h1>
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
            <div
              key={q.questionRef}
              className="flex flex-col gap-2 border-b border-rule pb-5 last:border-b-0 print:break-inside-avoid"
            >
              <div className="flex items-center gap-3 text-body-sm text-ink-faint">
                <span className="text-data-sm text-ink-muted">Q{q.position}</span>
                <span className="text-data-sm text-ink-muted">
                  {q.totalMarks} mark{q.totalMarks === 1 ? "" : "s"}
                </span>
                <span>{formatQuestionTopic(q.topic)}</span>
              </div>
              <p className="lm-prose whitespace-pre-line text-body-lg text-ink">{q.prompt}</p>
              {q.mcqOptions ? (
                // `ps-4`, not `pl-4`: logical inline-start padding, so the
                // option indent follows the reading direction (P3.4).
                <ul className="flex flex-col gap-1 ps-4 text-body-lg text-ink">
                  {q.mcqOptions.map((option) => (
                    <li key={option}>{option}</li>
                  ))}
                </ul>
              ) : (
                /* Answer space, on paper only. A worksheet whose questions run
                   straight into each other gives a student nowhere to write,
                   which defeats the one thing this screen is for.

                   Deliberately blank rather than `ruled-bg`: §8's print rule
                   strips every texture class from print output, so ruling here
                   would silently render as nothing. The space is functional and
                   the ruling would have been decoration, and decoration is
                   exactly what that rule excludes. */
                <div aria-hidden className="mt-1 hidden h-24 w-full print:block" />
              )}
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  )
}

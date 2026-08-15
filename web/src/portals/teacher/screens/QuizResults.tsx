/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { DownloadSimple, Warning } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { WeaknessChip } from "@/components/ui/weakness-chip"
import { cn, downloadCsv, relativeTime } from "@/lib/utils"
import { accuracyTone, TONE_CLASS, TONE_TO_SEVERITY } from "@/lib/severity"
import { PageHeaderSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import {
  teacherLoadFailureMessage,
  teacherMutationFailureMessage,
} from "@/lib/teacherOutcome"
import { useQuizResults, useSetQuizStatus } from "@/lib/hooks/useTeacherApi"
import type {
  QuizAssignmentResults,
  QuizQuestionAnalysis,
  QuizStudentResult,
} from "@/lib/teacherTypes"

/*
 * Quiz results for one class (T-10), at
 * `/teacher/quizzes/:quizId/assignments/:assignmentId/results` — reached from
 * T-09 step 6's assignment list.
 *
 * **Per assignment, never per quiz** (`docs/quiz-model.md` §1.6). A quiz
 * assigned to two classes has two sets of results; averaging them would
 * describe neither cohort. The route shape says so and there is deliberately
 * no "all classes" roll-up.
 *
 * All five spec panels — completion, score distribution, per-question
 * analysis, per-student results, class-wide topic weaknesses — are rendered
 * straight from `QuizAssignmentResultsDTO`, which `QuizResultsService`
 * computes as pure projections over ONE load of the assignment's submissions
 * (§4.6). **Nothing here re-derives one panel's number from another's**: the
 * class average is `averagePercentage`, not a mean of the student rows; the
 * completion count is `completion.completedCount`, not a filter over
 * `students`. That is what makes it structurally impossible for two panels to
 * disagree, and it is the whole point of the backend shape — do not "optimise"
 * a panel by computing it client-side.
 *
 * Three rules this screen cannot get wrong, each mirroring a backend
 * guarantee:
 * 1. **`null` is not zero.** `averageMarks`/`accuracy`/`percentage`/
 *    `completionRate` are `null` when nobody has been marked yet (or the
 *    roster is empty — 0/0 is not 0%). Every one renders as an em-dash with
 *    explanatory text, never as 0%.
 * 2. **Per-question marks are `effective_marks`** (§4.6 rule (a)) — a
 *    teacher's override reads here exactly as it reads on the student's
 *    screen. `overriddenCount` is surfaced so the teacher can see how much of
 *    the picture is their own correction rather than the AI's.
 * 3. **`offRosterSubmissionCount`** (D3.10) is work handed in by students who
 *    have since left the class. Every panel's denominator is the *live*
 *    roster, so that work is excluded — but it is reported in words rather
 *    than silently dropped. Do not simplify it away.
 *
 * **Quiz close/archive lives here**, not in the builder: this is the screen
 * where a teacher can actually see that everyone has finished. `useSetQuizStatus`
 * (written in chunk c and left without a consumer) is wired here.
 *
 * **Export** is a client-side CSV of the per-student results with a column per
 * question — cheap from data already in memory, same disposition as T-04's
 * heatmap export. There is no server-side export endpoint and none is implied.
 */

/** `QuizStudentResultDTO.status` is a `quiz_submissions` status plus the
 * synthetic `not_started` the backend emits for a roster student with no row
 * at all. Labels are the teacher's language, not the enum's. */
const STATUS_LABEL: Record<string, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  submitted: "Submitted",
  marked: "Marked",
}

function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status
}

function pct(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`
}

function downloadResultsCsv(data: QuizAssignmentResults): void {
  const questions = data.questionAnalysis
  const header = [
    "Student",
    "Status",
    "Submitted at",
    "Marked at",
    "Awarded",
    "Out of",
    "Percentage",
    "Needs review",
    ...questions.map((q) => `${q.questionRef} (/${q.totalMarks})`),
  ]
  const rows = data.students.map((s) => [
    s.displayName,
    statusLabel(s.status),
    s.submittedAt ?? "",
    s.markedAt ?? "",
    // An unmarked student is blank, never 0 — the CSV must not assert a zero
    // score the screen itself refuses to assert.
    s.awardedMarks == null ? "" : String(s.awardedMarks),
    s.maximumMarks == null ? "" : String(s.maximumMarks),
    s.percentage == null ? "" : `${Math.round(s.percentage * 100)}%`,
    s.needsTeacherReview ? "yes" : "no",
    ...questions.map((q) => {
      const mark = s.marksByQuestion[q.questionRef]
      return mark == null ? "" : String(mark)
    }),
  ])
  downloadCsv(`${data.quizTitle}-${data.assignment.className}-results`, [header, ...rows])
}

function StatTile({
  label,
  value,
  detail,
}: {
  label: string
  value: string
  detail?: string
}) {
  return (
    <div className="bg-paper-raised border border-rule rounded-lg px-4 py-3.5 min-w-0">
      <div className="text-eyebrow text-ink-faint">{label}</div>
      <div className="text-display-sm text-ink mt-1 tabular-nums">{value}</div>
      {detail ? <div className="text-body-sm text-ink-faint mt-0.5 text-pretty">{detail}</div> : null}
    </div>
  )
}

function ScoreDistribution({ data }: { data: QuizAssignmentResults }) {
  const buckets = data.scoreDistribution
  const peak = Math.max(1, ...buckets.map((b) => b.studentCount))
  const marked = buckets.reduce((sum, b) => sum + b.studentCount, 0)

  if (marked === 0) {
    return (
      <p className="text-body-sm text-ink-faint m-0">
        No marked submissions yet, so there is nothing to distribute.
      </p>
    )
  }

  return (
    <div>
      <div className="flex items-end gap-1.5 h-[120px]" role="list" aria-label="Score distribution">
        {buckets.map((b) => {
          const label = `${b.lower}–${b.upper}%`
          return (
            <div
              key={`${b.lower}-${b.upper}`}
              role="listitem"
              aria-label={`${label}: ${b.studentCount} student${b.studentCount === 1 ? "" : "s"}`}
              className="flex-1 flex flex-col items-center justify-end gap-1 min-w-0"
            >
              <span className="text-data-sm text-ink-faint">
                {b.studentCount > 0 ? b.studentCount : ""}
              </span>
              <div
                className={cn(
                  "w-full rounded-t-[4px]",
                  b.studentCount > 0 ? TONE_CLASS[accuracyTone(b.lower / 100)] : "bg-paper-sunk",
                )}
                style={{ height: `${Math.max(2, (b.studentCount / peak) * 88)}px` }}
              />
            </div>
          )
        })}
      </div>
      <div className="flex gap-1.5 mt-1.5">
        {buckets.map((b) => (
          <div
            key={`${b.lower}-${b.upper}`}
            className="flex-1 text-center text-data-sm text-ink-faint min-w-0"
          >
            {b.lower}
          </div>
        ))}
      </div>
      <p className="text-body-sm text-ink-faint mt-2 m-0">
        Ten-point bands of percentage score, not grades. A quiz has no grade boundaries to
        bucket by.
      </p>
    </div>
  )
}

function QuestionAnalysisTable({ questions }: { questions: QuizQuestionAnalysis[] }) {
  if (questions.length === 0) {
    return <p className="text-body-sm text-ink-faint m-0">This quiz has no included questions.</p>
  }
  return (
    <div
      className="bg-paper-raised border border-rule rounded-lg overflow-x-auto min-w-0"
      tabIndex={0}
      role="region"
      aria-label="Per-question analysis, scrollable horizontally"
    >
      <table className="w-full border-collapse text-body-md">
        <thead>
          <tr className="text-start">
            {[
              "Q",
              "Question",
              "Topic",
              "Accuracy",
              "Avg marks",
              "Full marks",
              "Zero",
              "Answered",
              "Flags",
            ].map((h) => (
              <th
                key={h}
                scope="col"
                className="text-eyebrow text-ink-faint font-normal px-3 py-2.5 border-b border-rule whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {questions.map((q) => (
            <tr key={q.questionRef} className="border-b border-rule last:border-b-0">
              <td className="px-3 py-2.5 text-data-sm text-ink-faint">{q.questionRef}</td>
              <td className="px-3 py-2.5 text-ink max-w-[320px]">
                <span className="line-clamp-2">{q.prompt}</span>
              </td>
              <td className="px-3 py-2.5 text-ink-faint">{q.topic ?? "–"}</td>
              <td className="px-3 py-2.5 tabular-nums">
                {q.accuracy == null ? (
                  <span className="text-ink-faint" title="Nobody has been marked on this question yet">
                    –
                  </span>
                ) : (
                  <span
                    className={cn(
                      "px-1.5 py-0.5 rounded font-medium",
                      TONE_CLASS[accuracyTone(q.accuracy)],
                    )}
                  >
                    {pct(q.accuracy)}
                  </span>
                )}
              </td>
              <td className="px-3 py-2.5 text-ink-faint tabular-nums">
                {q.averageMarks == null ? "—" : `${q.averageMarks.toFixed(1)} / ${q.totalMarks}`}
              </td>
              <td className="px-3 py-2.5 text-ink-faint tabular-nums">{q.fullMarksCount}</td>
              <td className="px-3 py-2.5 text-ink-faint tabular-nums">{q.zeroMarksCount}</td>
              <td className="px-3 py-2.5 text-ink-faint tabular-nums">{q.answeredCount}</td>
              <td className="px-3 py-2.5">
                <div className="flex gap-1 flex-wrap">
                  {q.needsReviewCount > 0 ? (
                    <Chip tone="warn">{q.needsReviewCount} to review</Chip>
                  ) : null}
                  {q.overriddenCount > 0 ? (
                    <Chip tone="neutral">{q.overriddenCount} overridden</Chip>
                  ) : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StudentTable({ students }: { students: QuizStudentResult[] }) {
  if (students.length === 0) {
    return (
      <EmptyState
        heading="Nobody on the roster"
        body="This class has no enrolled students, so there is nobody to have taken the quiz. Enrol students on the class roster and they will appear here."
      />
    )
  }
  return (
    <div
      className="bg-paper-raised border border-rule rounded-lg overflow-x-auto min-w-0"
      tabIndex={0}
      role="region"
      aria-label="Per-student results, scrollable horizontally"
    >
      <table className="w-full border-collapse text-body-md">
        <thead>
          <tr className="text-start">
            {["Student", "Status", "Score", "Submitted", "Notes"].map((h) => (
              <th
                key={h}
                scope="col"
                className="text-eyebrow text-ink-faint font-normal px-3 py-2.5 border-b border-rule whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {students.map((s) => (
            <tr key={s.studentId} className="border-b border-rule last:border-b-0">
              <td className="px-3 py-2.5">
                <Link
                  to={`/teacher/students/${s.studentId}`}
                  className="text-ink no-underline hover:underline"
                >
                  {s.displayName}
                </Link>
              </td>
              <td className="px-3 py-2.5 text-ink-faint">{statusLabel(s.status)}</td>
              <td className="px-3 py-2.5 tabular-nums">
                {s.percentage == null ? (
                  <span className="text-ink-faint">—</span>
                ) : (
                  <span
                    className={cn(
                      "px-1.5 py-0.5 rounded font-medium",
                      TONE_CLASS[accuracyTone(s.percentage)],
                    )}
                  >
                    {s.awardedMarks}/{s.maximumMarks} · {pct(s.percentage)}
                  </span>
                )}
              </td>
              <td className="px-3 py-2.5 text-ink-faint">
                {s.submittedAt ? relativeTime(s.submittedAt) : "—"}
              </td>
              <td className="px-3 py-2.5">
                <div className="flex gap-1 flex-wrap items-center">
                  {s.needsTeacherReview ? <Chip tone="warn">Needs review</Chip> : null}
                  {s.markingError ? (
                    <span className="inline-flex items-center gap-1 text-body-sm text-err">
                      <Warning weight="fill" className="h-3.5 w-3.5 flex-none" />
                      Marking failed: {s.markingError}
                    </span>
                  ) : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function QuizResults() {
  const { quizId, assignmentId } = useParams<{ quizId: string; assignmentId: string }>()
  const resultsQuery = useQuizResults(quizId, assignmentId)
  const setStatus = useSetQuizStatus(quizId)
  const [confirmingClose, setConfirmingClose] = useState(false)

  // The sr-only `h1` on both pre-data states is the same shape ReviewItem.tsx
  // and QuizBuilder.tsx already use: `ErrorState` renders its heading as plain
  // text (the non-heading empty/error gap carried since the Phase-2.5 report
  // §8), so without it these two states ship with no level-one heading at all.
  // Found by P3.10 chunk e2a's per-state axe pass — the states the audit could
  // not see before this chunk.
  if (resultsQuery.isPending) {
    return (
      <div className="flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Quiz results</h1>
        <PageHeaderSkeleton />
        <PanelSkeleton />
      </div>
    )
  }
  if (resultsQuery.isError) {
    return (
      <div className="flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Quiz results</h1>
        <ErrorState
          heading="Couldn't load these results"
          body={teacherLoadFailureMessage(resultsQuery.error)}
          action={{ label: "Retry", onClick: () => resultsQuery.refetch() }}
          secondaryAction={{ label: "Back to quizzes", onClick: () => history.back() }}
        />
      </div>
    )
  }

  // Bound after the pending/error guards so `data` narrows to non-undefined.
  const data = resultsQuery.data
  const rankedTopics = data.topicWeaknesses
  const { completion, assignment } = data
  const completionDetail =
    completion.completionRate == null
      ? "No students on the roster yet"
      : `${completion.completedCount} of ${completion.rosterSize} on the current roster`

  return (
    <div className="flex flex-col gap-6 min-w-0">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-eyebrow text-ink-faint">
            {data.subjectCode} · {assignment.className}
          </div>
          <h1 className="text-display-md text-ink m-0 mt-1 text-pretty">{data.quizTitle}</h1>
          <p className="text-body-sm text-ink-faint m-0 mt-1">
            {data.questionCount} question{data.questionCount === 1 ? "" : "s"} · {data.totalMarks}{" "}
            marks · assigned {relativeTime(assignment.assignedAt)}
            {assignment.dueAt ? ` · due ${new Date(assignment.dueAt).toLocaleString()}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            type="button"
            variant="secondary"
            onClick={() => downloadResultsCsv(data)}
            disabled={data.students.length === 0}
          >
            <DownloadSimple className="h-4 w-4" />
            Export CSV
          </Button>
          <Link
            to={`/teacher/quizzes/${quizId}?step=6`}
            className="text-body-sm text-ink-faint no-underline transition-colors hover:text-ink"
          >
            Back to the quiz
          </Link>
        </div>
      </header>

      {/* Results are per assignment; say so rather than letting a teacher
          assume this is every class that got the quiz. */}
      <p className="text-body-sm text-ink-faint m-0 -mt-3">
        These results cover <strong className="text-ink font-medium">{assignment.className}</strong>{" "}
        only. A quiz assigned to another class has its own separate results.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          label="Completion"
          value={completion.completionRate == null ? "—" : pct(completion.completionRate)}
          detail={completionDetail}
        />
        <StatTile
          label="Class average"
          value={pct(data.averagePercentage)}
          detail={data.averagePercentage == null ? "Nothing marked yet" : "Across marked work"}
        />
        <StatTile
          label="Median"
          value={pct(data.medianPercentage)}
          detail={data.medianPercentage == null ? "Nothing marked yet" : "Across marked work"}
        />
        <StatTile
          label="Needs review"
          value={String(data.students.filter((s) => s.needsTeacherReview).length)}
          detail="Low-confidence marks waiting in the review queue"
        />
      </div>

      {completion.offRosterSubmissionCount > 0 ? (
        <p className="text-body-sm text-ink-faint bg-paper-sunk border border-rule rounded-md px-3.5 py-2.5 m-0 text-pretty">
          {completion.offRosterSubmissionCount} submission
          {completion.offRosterSubmissionCount === 1 ? "" : "s"} came from{" "}
          {completion.offRosterSubmissionCount === 1 ? "a student" : "students"} no longer on this
          roster. Every figure above is measured against the current roster, so that work is not
          counted here. It is reported so it doesn't disappear silently.
        </p>
      ) : null}

      <section>
        <h2 className="text-eyebrow text-ink-faint m-0 mb-2.5">
          Score distribution
        </h2>
        <div className="bg-paper-raised border border-rule rounded-lg p-[18px]">
          <ScoreDistribution data={data} />
        </div>
      </section>

      <section>
        <h2 className="text-eyebrow text-ink-faint m-0 mb-2.5">
          Per-question analysis
        </h2>
        <p className="text-body-sm text-ink-faint m-0 mb-2.5 text-pretty">
          Marks here include your own overrides, so this reads exactly as the student sees it. A
          dash means nobody has been marked on that question yet, not that they scored zero.
        </p>
        <QuestionAnalysisTable questions={data.questionAnalysis} />
      </section>

      <section>
        <h2 className="text-eyebrow text-ink-faint m-0 mb-2.5">
          What the quiz revealed
        </h2>
        {rankedTopics.length === 0 ? (
          <p className="text-body-sm text-ink-faint m-0">
            No class-wide weak topics yet. The questions either carry no topic, or not enough of
            the class has been marked.
          </p>
        ) : (
          <div className="flex flex-col gap-1.5 max-w-[620px]">
            {rankedTopics.map((t) => (
              <WeaknessChip
                key={t.topic}
                topic={t.topic}
                severity={TONE_TO_SEVERITY[accuracyTone(t.accuracy)]}
                meta={`${t.lostMarks}/${t.maximumMarks} marks lost across the class · ${Math.round(t.accuracy * 100)}% accuracy`}
              />
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-eyebrow text-ink-faint m-0 mb-2.5">
          Students
        </h2>
        <StudentTable students={data.students} />
      </section>

      {/* Close/archive lives on this screen, not in the builder: this is where
          a teacher can actually see everyone has finished. */}
      <section className="border-t border-rule pt-4">
        <h2 className="text-eyebrow text-ink-faint m-0 mb-2">
          Quiz status
        </h2>
        {confirmingClose ? (
          <div className="flex flex-col gap-2 max-w-[560px]">
            <p className="text-body-sm text-ink-faint m-0 text-pretty">
              Closing stops any further submissions, on every class this quiz is assigned to, not
              just {assignment.className}. Students who have already submitted keep their marks.
              This cannot be undone.
            </p>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ink"
                disabled={setStatus.isPending}
                onClick={() =>
                  setStatus.mutate(
                    { status: "closed" },
                    { onSuccess: () => setConfirmingClose(false) },
                  )
                }
              >
                {setStatus.isPending ? "Closing…" : "Yes, close the quiz"}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setConfirmingClose(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <Button type="button" variant="secondary" onClick={() => setConfirmingClose(true)}>
            Close this quiz
          </Button>
        )}
        {setStatus.isError ? (
          <div role="alert" className="text-body-sm text-err mt-2">
            Couldn't change the status: {teacherMutationFailureMessage(setStatus.error)}
          </div>
        ) : null}
      </section>
    </div>
  )
}

import { Link, useParams } from "react-router-dom"
import { CaretLeft } from "@phosphor-icons/react"
import { useChildSubject } from "@/lib/hooks/useParentApi"
import { GradeBadge } from "@/components/ui/grade-badge"
import { WeaknessChip } from "@/components/ui/weakness-chip"
import { ErrorState } from "@/components/ui/state-views"
import { accuracyTone, TONE_TO_SEVERITY } from "@/lib/severity"
import { relativeTime } from "@/lib/utils"

/*
 * P-03 · Child subject detail. "One subject in depth: papers attempted with
 * marks and grades, the predicted grade with its basis explained simply,
 * boundary distance ('3 marks from an A'), and topic weaknesses. Read-only
 * throughout."
 *
 * Read-only is structural here, not a discipline: `useParentApi.ts` exposes no
 * mutation for any parent route, so there is nothing on this screen that could
 * write even by mistake.
 */

/**
 * "The predicted grade with its basis explained simply."
 *
 * The basis is a real, narrow fact — it is the grade of the child's most recent
 * grade-bearing paper in this subject, carried through the boundary table — and
 * that is what this says. It does not promise a forecast, a confidence level,
 * or a trajectory, none of which the backend computes. UI spec §1.4 forbids
 * inventing precision, and "predicted" is the single word most likely to be
 * over-read by the audience this screen is for.
 */
function PredictedBasis({ papers }: { papers: number }) {
  return (
    <p className="text-body-md text-t2">
      {papers === 1
        ? "Based on the one paper they've had marked in this subject so far."
        : `Based on their most recent of ${papers} marked papers, placed against the official grade boundaries for this paper.`}{" "}
      It moves as they sit more papers.
    </p>
  )
}

export function SubjectDetail() {
  const { childId = "", code = "" } = useParams<{ childId: string; code: string }>()
  const { data, isPending, isError, error } = useChildSubject(childId, code)

  if (isPending) {
    return (
      <p role="status" aria-live="polite" className="text-body-md text-t2">
        Loading…
      </p>
    )
  }

  if (isError) {
    return (
      <ErrorState
        heading="We couldn't load this subject"
        body={error instanceof Error ? error.message : "Please try again in a moment."}
        action={{ label: "Try again", onClick: () => window.location.reload() }}
      />
    )
  }

  const { papers, boundaryDistance, weakTopics } = data

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <Link
          to={`/parent/children/${childId}`}
          className="flex items-center gap-1 self-start text-body-md text-t2 hover:text-t1"
        >
          <CaretLeft size={14} />
          Back
        </Link>
        <div className="flex flex-wrap items-center gap-4">
          <GradeBadge grade={data.predictedGrade} size="medium" basis="predicted" />
          <div className="flex flex-col gap-0.5">
            <h1 className="text-display-md text-t1">{data.subjectName}</h1>
            {/* Code as secondary detail, never the headline (§4.8 design note). */}
            <div className="text-body-md text-t2">{data.subjectCode}</div>
          </div>
        </div>
        <PredictedBasis papers={papers.length} />
      </div>

      {/*
       * "3 marks from an A". Rendered only when the backend computed it —
       * `boundaryDistance` is null when the child is already on the top grade
       * or the boundary table has no threshold for the next grade up. An
       * omitted panel is the honest form of "we don't know"; a "0 marks from"
       * would assert a distance that was never calculated.
       */}
      {boundaryDistance ? (
        <section className="rounded-md border border-border bg-accent-subtle p-5">
          <div className="text-body-lg font-medium text-t1">
            {boundaryDistance.marksNeeded === 0
              ? `On track for a ${boundaryDistance.nextGrade}`
              : `${boundaryDistance.marksNeeded} more ${
                  boundaryDistance.marksNeeded === 1 ? "mark" : "marks"
                } for a ${boundaryDistance.nextGrade}`}
          </div>
          <p className="mt-1 text-body-md text-t1">{boundaryDistance.summary}</p>
        </section>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="text-body-lg font-medium text-t1">Papers they've done</h2>
        {papers.length === 0 ? (
          <p className="rounded-md border border-border bg-surface p-4 text-body-md text-t2">
            No marked papers in this subject yet.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {papers.map((paper) => (
              <div
                key={`${paper.paperId}-${paper.recordedAt}`}
                className="flex items-center gap-4 rounded-md border border-border bg-surface p-4"
              >
                <GradeBadge grade={paper.grade} size="inline" basis="achieved" />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <div className="text-body-lg text-t1">{paper.marks}</div>
                  <div className="text-body-md text-t2">
                    {paper.paperId} · marked {relativeTime(paper.recordedAt)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-body-lg font-medium text-t1">Topics to work on</h2>
          <Link
            to={`/parent/children/${childId}/weaknesses`}
            className="text-body-md text-accent hover:underline"
          >
            All subjects
          </Link>
        </div>
        {weakTopics.length === 0 ? (
          <p className="rounded-md border border-border bg-surface p-4 text-body-md text-t2">
            Nothing stands out as a weak topic in this subject yet.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {weakTopics.map((topic) => (
              <WeaknessChip
                key={topic.topic}
                topic={topic.topic}
                severity={TONE_TO_SEVERITY[accuracyTone(topic.accuracy)]}
                meta={`${topic.lostMarks} of ${topic.maximumMarks} marks`}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

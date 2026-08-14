/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Link, useParams } from "react-router-dom"
import { useChildSubject } from "@/lib/hooks/useParentApi"
import { GradeBadge } from "@/components/ui/grade-badge"
import { WeaknessChip } from "@/components/ui/weakness-chip"
import { ErrorState } from "@/components/ui/state-views"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { parentLoadFailureMessage } from "@/lib/parentOutcome"
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
 * write even by mistake. That is also why `parentOutcome.ts` has no
 * write-failure helper for it to call.
 *
 * The screen's own "‹ Back" link is gone (P4.6): the shell's breadcrumb row
 * sits immediately above it and goes to the same place, and that row now names
 * the subject rather than reading "This subject". See `ParentTrail`.
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
/**
 * "a" or "an" for a letter grade.
 *
 * The capture round photographed "6 more marks for a A", which is what a
 * template that hardcodes the article produces for exactly the grades a parent
 * most wants to read about. IGCSE grades are single letters, so the rule is
 * the letter's *name*, not its spelling: A, A*, E and F are vowel-initial when
 * spoken ("an A", "an E", "an F"), the rest are not. This is spelled out
 * rather than reduced to a vowel test because "F" would fail a vowel test and
 * "U" would pass one.
 */
export function gradeArticle(grade: string): "a" | "an" {
  return /^[AEF]/.test(grade.trim()) ? "an" : "a"
}

function PredictedBasis({ papers }: { papers: number }) {
  return (
    <p className="max-w-prose text-body-md text-ink-muted">
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
      <div className="flex flex-col gap-8">
        <PageHeaderSkeleton />
        <ListSkeleton rows={3} />
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorState
        heading="We couldn't load this subject"
        body={parentLoadFailureMessage(error)}
        action={{ label: "Try again", onClick: () => window.location.reload() }}
      />
    )
  }

  const { papers, boundaryDistance, weakTopics } = data

  return (
    <div className="flex flex-col gap-8">
      <div className="margin-rule flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <GradeBadge grade={data.predictedGrade} size="medium" basis="predicted" />
          <div className="flex flex-col gap-0.5">
            <h1 className="text-display-lg text-ink">{data.subjectName}</h1>
            {/* Code as secondary detail, never the headline (§4.8 design
                note), and on the data face, which is what a syllabus code is. */}
            <div className="text-data-sm text-ink-faint">{data.subjectCode}</div>
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
        /*
         * The tone is `info`, and that is a fix rather than a preference.
         * This panel shipped on `--accent-wash`, which on this palette sits a
         * hair away from `--err-wash` — the two are the same washed red to
         * anything but a measuring instrument, and DESIGN.md §3.4 and §3.6
         * list their values side by side. So "6 more marks for an A", the
         * most encouraging sentence on the screen, was
         * rendered in the register the product uses for failures, to the
         * audience least equipped to know that was not deliberate. This is
         * surface 5's finding (d) again, where "Assigned" was accent-toned and
         * a healthy live state read as alarm. `info` is the right register:
         * §3.6 gives it to neutral notices and "how this works", and a
         * distance to the next boundary is a fact, not a verdict either way.
         */
        <section className="rounded-lg border border-rule bg-info-wash p-6">
          <div className="text-display-sm text-info">
            {boundaryDistance.marksNeeded === 0
              ? `On track for ${gradeArticle(boundaryDistance.nextGrade)} ${boundaryDistance.nextGrade}`
              : `${boundaryDistance.marksNeeded} more ${
                  boundaryDistance.marksNeeded === 1 ? "mark" : "marks"
                } for ${gradeArticle(boundaryDistance.nextGrade)} ${boundaryDistance.nextGrade}`}
          </div>
          <p className="mt-1.5 text-body-md text-ink">{boundaryDistance.summary}</p>
        </section>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="text-display-md text-ink">Papers they've done</h2>
        {papers.length === 0 ? (
          <p className="rounded-lg border border-rule bg-paper-raised p-5 text-body-md text-ink-muted">
            No marked papers in this subject yet.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {papers.map((paper) => (
              <div
                key={`${paper.paperId}-${paper.recordedAt}`}
                className="flex items-center gap-4 rounded-lg border border-rule bg-paper-raised p-5"
              >
                <GradeBadge grade={paper.grade} size="inline" basis="achieved" />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  {/* The mark is the row's headline and it is a figure, so it
                      is set in the data face rather than the body face. */}
                  <div className="text-data-md text-ink">{paper.marks}</div>
                  <div className="text-body-sm text-ink-muted">
                    <span className="text-data-sm">{paper.paperId}</span> · marked{" "}
                    {relativeTime(paper.recordedAt)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-display-md text-ink">Topics to work on</h2>
          <Link
            to={`/parent/children/${childId}/weaknesses`}
            className="rounded-sm pointer-coarse:inline-flex pointer-coarse:items-center pointer-coarse:min-h-11 text-body-sm text-accent-ink transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            All subjects
          </Link>
        </div>
        {weakTopics.length === 0 ? (
          <p className="rounded-lg border border-rule bg-paper-raised p-5 text-body-md text-ink-muted">
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

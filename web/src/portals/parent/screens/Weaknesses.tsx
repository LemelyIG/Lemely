/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useParams } from "react-router-dom"
import { useChildWeaknesses } from "@/lib/hooks/useParentApi"
import { ErrorState } from "@/components/ui/state-views"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { parentLoadFailureMessage } from "@/lib/parentOutcome"
import { accuracyTone, TONE_CLASS } from "@/lib/severity"
import type { WeakTopic } from "@/lib/parentTypes"

/*
 * P-04 · Child weaknesses. "Ranked weak topics with what they're costing,
 * phrased for a non-specialist, and constructive framing on what the child is
 * doing about it (practice generated, sessions planned). Explicitly not a list
 * of failures."
 *
 * ── "Explicitly not a list of failures", made concrete ──────────────────────
 * The same numbers can be a report card or a plan depending entirely on how
 * they are framed, and this audience will read whichever one we write. So:
 * the heading is what to work on, each row leads with the marks that are
 * *available* rather than the marks that were lost, and the page opens by
 * saying plainly that every child has a list like this. The underlying figures
 * are unchanged and unrounded — the framing is honest, not softened.
 *
 * ── The gap this screen must NOT fake ───────────────────────────────────────
 * "What the child is doing about it (practice generated, sessions planned)"
 * has no data source. `ChildWeaknessesDTO` carries no such field, and P3.6
 * chunk a's router docstring records why: the study-plan machinery is keyed by
 * the authenticated caller, never by a caller-supplied child id, so there is
 * no link between a stored plan and *a child viewed by a parent*. D3.11 chose
 * to report that as absent rather than ship "sessions planned: 0", which would
 * read as "your child is doing nothing" — a claim the data does not make. The
 * closing note below says what the product does and does not yet show, which
 * is the honest version of the constructive framing the spec asked for.
 */

/** Rows are rendered in the backend's order (worst accuracy first) and are
 * never re-sorted here — `ChildWeaknessesDTO` documents the ranking as its
 * own, and a second ordering rule would be a second authority on "worst". */
function TopicRow({ topic, rank }: { topic: WeakTopic; rank: number }) {
  const tone = accuracyTone(topic.accuracy)
  const scored = topic.maximumMarks - topic.lostMarks

  return (
    /*
     * Column below `sm`, row above it. The capture round at 375 showed the
     * accuracy chip sitting beside the topic title and taking half the width,
     * so "Moments and equilibrium" wrapped to two lines with the sentence
     * beneath it wrapping to three: a four-row list became a wall. The chip is
     * the least urgent thing in the row and it is the thing that moves.
     */
    <li className="flex flex-col items-start gap-3 rounded-lg border border-rule bg-paper-raised p-5 sm:flex-row sm:items-start sm:gap-4">
      <div className="flex w-full min-w-0 flex-1 items-start gap-4">
        {/* The `<ol>` already carries the order for a screen reader, so the
            printed rank is a scanning aid and nothing else. */}
        <span
          aria-hidden="true"
          className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-paper-sunk text-data-sm text-ink-muted"
        >
          {rank}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="text-body-lg font-medium text-ink">{topic.topic}</div>
          {/* Leads with what is there to gain, not with what was lost. Both
              numbers are the real ones; only the order of mention is a choice. */}
          <div className="text-body-sm text-ink-muted">
            {topic.lostMarks} {topic.lostMarks === 1 ? "mark" : "marks"} to gain here. They've
            scored {scored} of {topic.maximumMarks} on this topic so far.
          </div>
        </div>
      </div>
      {/*
       * The figure is labelled, and that is the fix rather than the styling.
       * It shipped as a bare tone-coloured "62%" pinned to the row's end, which
       * is the third time this surface family has produced an unlabelled
       * number in a coloured chip: surface 4's rank column and surface 5's
       * review-queue confidence were the first two. A parent scanning a list
       * headed "what to work on" has every reason to read an unlabelled
       * percentage as a score out of a hundred, and it is not one — it is the
       * share of the marks available on this topic that the child has taken.
       * The colour is never the only signal: the percentage is written out,
       * and now so is what it counts.
       */}
      <span
        // Stacked and end-aligned in the desktop row; a single baseline-aligned
        // line at mobile, where it sits under the text and has the width for it.
        className={`ms-11 flex flex-none items-baseline gap-2 rounded-md px-2.5 py-1.5 sm:ms-0 sm:flex-col sm:items-end sm:gap-0.5 ${TONE_CLASS[tone]}`}
      >
        <span className="text-data-md">{Math.round(topic.accuracy * 100)}%</span>
        <span className="text-body-sm">of marks taken</span>
      </span>
    </li>
  )
}

export function Weaknesses() {
  const { childId = "" } = useParams<{ childId: string }>()
  const { data, isPending, isError, error } = useChildWeaknesses(childId)

  if (isPending) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeaderSkeleton />
        <ListSkeleton rows={4} />
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorState
        heading="We couldn't load this"
        body={parentLoadFailureMessage(error)}
        action={{ label: "Try again", onClick: () => window.location.reload() }}
      />
    )
  }

  const topics = data.weakTopics

  return (
    <div className="flex flex-col gap-6">
      <div className="margin-rule flex flex-col gap-2">
        <h1 className="text-display-lg text-ink">What to work on next</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          Every student has a list like this. It is what marking is for. These are the topics
          where the most marks are currently going, strongest signal first.
        </p>
      </div>

      {topics.length === 0 ? (
        <p className="rounded-lg border border-rule bg-paper-raised p-5 text-body-md text-ink-muted">
          Nothing stands out yet. Weak topics appear here once a few papers have been marked.
        </p>
      ) : (
        <ol className="flex flex-col gap-2">
          {topics.map((topic, index) => (
            <TopicRow key={topic.topic} topic={topic} rank={index + 1} />
          ))}
        </ol>
      )}

      {/* The absent signal, named rather than stubbed (see the module header). */}
      <p className="rounded-lg border border-dashed border-rule p-5 text-body-sm text-ink-muted">
        Lemely doesn't yet show parents what practice has been set on these topics. Their
        teacher can see the same list, and it's a good thing to ask about.
      </p>
    </div>
  )
}

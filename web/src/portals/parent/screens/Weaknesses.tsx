import { Link, useParams } from "react-router-dom"
import { CaretLeft } from "@phosphor-icons/react"
import { useChildWeaknesses } from "@/lib/hooks/useParentApi"
import { ErrorState } from "@/components/ui/state-views"
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
    <li className="flex items-start gap-4 rounded-md border border-border bg-surface p-4">
      <span
        aria-hidden="true"
        className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-surface-2 text-body-md text-t2"
      >
        {rank}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="text-body-lg text-t1">{topic.topic}</div>
        {/* Leads with what is there to gain, not with what was lost. Both
            numbers are the real ones; only the order of mention is a choice. */}
        <div className="text-body-md text-t2">
          {topic.lostMarks} {topic.lostMarks === 1 ? "mark" : "marks"} to gain here — they've
          scored {scored} of {topic.maximumMarks} on this topic so far.
        </div>
      </div>
      <span
        className={`flex-none rounded px-2 py-1 text-body-md ${TONE_CLASS[tone]}`}
        // The colour is never the only signal: the percentage is written out.
      >
        {Math.round(topic.accuracy * 100)}%
      </span>
    </li>
  )
}

export function Weaknesses() {
  const { childId = "" } = useParams<{ childId: string }>()
  const { data, isPending, isError, error } = useChildWeaknesses(childId)

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
        heading="We couldn't load this"
        body={error instanceof Error ? error.message : "Please try again in a moment."}
        action={{ label: "Try again", onClick: () => window.location.reload() }}
      />
    )
  }

  const topics = data.weakTopics

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Link
          to={`/parent/children/${childId}`}
          className="flex items-center gap-1 self-start text-body-md text-t2 hover:text-t1"
        >
          <CaretLeft size={14} />
          Back
        </Link>
        <h1 className="text-display-md text-t1">What to work on next</h1>
        <p className="text-body-md text-t2">
          Every student has a list like this — it's what marking is for. These are the topics
          where the most marks are currently going, strongest signal first.
        </p>
      </div>

      {topics.length === 0 ? (
        <p className="rounded-md border border-border bg-surface p-4 text-body-md text-t2">
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
      <p className="rounded-md border border-dashed border-border p-4 text-body-md text-t2">
        Lemely doesn't yet show parents what practice has been set on these topics. Their
        teacher can see the same list, and it's a good thing to ask about.
      </p>
    </div>
  )
}

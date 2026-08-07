import { Link, useParams } from "react-router-dom"
import { CaretLeft, CaretRight } from "@phosphor-icons/react"
import { useChildOverview, useChildren } from "@/lib/hooks/useParentApi"
import { GradeBadge } from "@/components/ui/grade-badge"
import { TrendSparkline } from "@/components/ui/trend-sparkline"
import { WeaknessChip } from "@/components/ui/weakness-chip"
import { ErrorState } from "@/components/ui/state-views"
import { accuracyTone, TONE_TO_SEVERITY } from "@/lib/severity"
import { relativeTime } from "@/lib/utils"
import type { ParentAtRiskFlag, SubjectOverview, WeakTopic } from "@/lib/parentTypes"

/*
 * P-02 · Child overview. The screen a parent actually came for, and by the
 * spec's own measure ("two taps from login") the deepest most will ever go.
 *
 * Section order is the spec's stated priority, not visual convenience:
 * activity comes first because "parents ask this first", then anything at
 * risk, then subjects, then papers, then weak topics.
 *
 * ── The design note, applied ────────────────────────────────────────────────
 * "A parent should not need to know what '0580/42 Variant 2' means. Say 'Maths
 * — Paper 4' and keep the code as secondary detail." Every paper here leads
 * with `subjectName` (translated server-side via the det profile, falling back
 * to the raw code — never invented) and carries `paperId` as muted secondary
 * text. The code is not hidden — a parent forwarding a screenshot to a tutor
 * needs it — it is just not the headline.
 */

/** Grade ladder position is the backend's business; this screen only ever
 * renders `predictedGrade` as *predicted*. It is the same value T-03/T-05/T-06
 * render with `basis="predicted"` (P3.7 chunk d had to correct exactly this
 * inconsistency once) — the same number must not read differently on two
 * screens, and least of all across two audiences. */
function SubjectRow({ childId, subject }: { childId: string; subject: SubjectOverview }) {
  return (
    <Link
      to={`/parent/children/${childId}/subjects/${subject.subjectCode}`}
      className="flex items-center gap-4 rounded-md border border-border bg-surface p-4 hover:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <GradeBadge grade={subject.predictedGrade} size="inline" basis="predicted" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="text-body-lg text-t1">{subject.subjectName}</div>
        <div className="text-body-md text-t2">
          {subject.subjectCode} ·{" "}
          {subject.paperCount === 1 ? "1 paper" : `${subject.paperCount} papers`} · latest{" "}
          {Math.round(subject.latestPercentage)}%
        </div>
        {/*
         * "Predicted grade against target grade" — there is no target-grade
         * column anywhere until Phase 4's onboarding questionnaire (D3.3 /
         * D3.11), so `target` is always null today. It is stated as absent
         * rather than defaulted: a defaulted target would make every child
         * look on track, which is precisely the invented precision UI spec
         * §1.4 forbids. When P4 lands, this branch starts rendering on its own.
         */}
        <div className="text-body-md text-t2">
          {subject.target
            ? `Target ${subject.target}`
            : "No target grade set yet — you can set one when goals arrive."}
        </div>
      </div>
      {subject.trend.length > 1 ? (
        <TrendSparkline
          values={subject.trend.map((point) => point.percentage)}
          className="hidden flex-none sm:flex"
        />
      ) : null}
      <CaretRight size={16} className="flex-none text-t3" aria-hidden="true" />
    </Link>
  )
}

/**
 * At-risk flags "with their reason explained without jargon".
 *
 * The backend's `summary` is written for a teacher — "Declining over the last
 * 3 papers: 62% -> 55% -> 48% (14pp drop)" — and "14pp" is jargon by any
 * reasonable reading. So this rephrases from the flag's *structured evidence*,
 * which is the same data the summary was built from; no fact is added or
 * softened, only worded for a non-specialist.
 *
 * Anything without a hand-written parent phrasing falls back to the backend's
 * own `summary`. That fallback is deliberate: `below_target` cannot fire at all
 * until Phase 4 (D3.3 reports it *not evaluable*, never as a pass), and writing
 * parent copy for a rule that has never produced a flag would be guessing at
 * wording for data nobody has seen.
 */
function atRiskCopy(flag: ParentAtRiskFlag): { title: string; body: string } {
  if (flag.reason === "declining_trend") {
    const percentages = flag.evidence.percentages
    const trail = Array.isArray(percentages)
      ? percentages.map((p) => `${Math.round(p)}%`).join(", then ")
      : null
    return {
      title: "Their marks have been falling",
      body: trail
        ? `Across their last few papers they scored ${trail}. It may be worth asking what changed.`
        : flag.summary,
    }
  }
  if (flag.reason === "inactive") {
    const days = flag.evidence.daysInactive
    const lastActive = flag.evidence.lastActiveAt
    return {
      title: "They haven't worked in a while",
      body:
        typeof days === "number"
          ? `Nothing has been submitted for ${days} days${
              typeof lastActive === "string"
                ? ` — the last was ${relativeTime(lastActive)}`
                : ""
            }.`
          : flag.summary,
    }
  }
  return { title: "Something to look at", body: flag.summary }
}

function AtRiskPanel({ flags }: { flags: ParentAtRiskFlag[] }) {
  if (flags.length === 0) return null
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-body-lg font-medium text-t1">Worth a conversation</h2>
      {flags.map((flag) => {
        const copy = atRiskCopy(flag)
        return (
          <div
            key={flag.reason}
            className="flex flex-col gap-1 rounded-md border border-border bg-warn-bg p-4"
          >
            <div className="text-body-lg font-medium text-t1">{copy.title}</div>
            <p className="text-body-md text-t1">{copy.body}</p>
          </div>
        )
      })}
      {/* UI spec §1.4: flags are signals, not verdicts. Said plainly, to the
          audience most likely to read one as a verdict. */}
      <p className="text-body-md text-t2">
        These are signals to look into, not conclusions. Their teacher sees the same ones.
      </p>
    </section>
  )
}

function WeakTopicList({ topics, childId }: { topics: WeakTopic[]; childId: string }) {
  if (topics.length === 0) return null
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-body-lg font-medium text-t1">Topics they're finding hard</h2>
        <Link
          to={`/parent/children/${childId}/weaknesses`}
          className="text-body-md text-accent hover:underline"
        >
          See all
        </Link>
      </div>
      <div className="flex flex-wrap gap-2">
        {topics.slice(0, 6).map((topic) => (
          <WeaknessChip
            key={topic.topic}
            topic={topic.topic}
            severity={TONE_TO_SEVERITY[accuracyTone(topic.accuracy)]}
            meta={`${topic.lostMarks} of ${topic.maximumMarks} marks lost`}
          />
        ))}
      </div>
    </section>
  )
}

export function ChildOverview() {
  const { childId = "" } = useParams<{ childId: string }>()
  const { data, isPending, isError, error } = useChildOverview(childId)
  // Shares P-01's cache — this is only to decide whether "back to your
  // children" is a real destination, never a second source for child data.
  const { data: childList } = useChildren()
  const hasSiblings = (childList?.children.length ?? 0) > 1

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

  const { activity, subjects, recentPapers, weakTopics, atRiskFlags } = data

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        {hasSiblings ? (
          <Link
            to="/parent"
            className="flex items-center gap-1 self-start text-body-md text-t2 hover:text-t1"
          >
            <CaretLeft size={14} />
            Your children
          </Link>
        ) : null}
        <h1 className="text-display-md text-t1">{data.displayName}</h1>
      </div>

      {/* "Activity summary (how much they've been working — parents ask this
          first)." So it is first. Absence is stated as absence: a child with
          no records reads "nothing yet", never "0 days ago". */}
      <section className="flex flex-wrap gap-3">
        <div className="min-w-40 flex-1 rounded-md border border-border bg-surface p-4">
          <div className="text-label-sm uppercase tracking-wide text-t2">Papers marked</div>
          <div className="mt-1 text-display-md text-t1">{activity.totalPapers}</div>
        </div>
        <div className="min-w-40 flex-1 rounded-md border border-border bg-surface p-4">
          <div className="text-label-sm uppercase tracking-wide text-t2">Last worked</div>
          <div className="mt-1 text-body-lg text-t1">
            {activity.lastActiveAt ? relativeTime(activity.lastActiveAt) : "Nothing yet"}
          </div>
          {activity.daysSinceLastActivity !== null ? (
            <div className="mt-0.5 text-body-md text-t2">
              {activity.daysSinceLastActivity === 0
                ? "Today"
                : `${activity.daysSinceLastActivity} days ago`}
            </div>
          ) : null}
        </div>
      </section>

      <AtRiskPanel flags={atRiskFlags} />

      <section className="flex flex-col gap-3">
        <h2 className="text-body-lg font-medium text-t1">Subjects</h2>
        {subjects.length === 0 ? (
          <p className="rounded-md border border-border bg-surface p-4 text-body-md text-t2">
            No marked papers yet. Subjects appear here once {data.displayName} has had a paper
            marked.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {subjects.map((subject) => (
              <SubjectRow key={subject.subjectCode} childId={childId} subject={subject} />
            ))}
          </div>
        )}
      </section>

      {recentPapers.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-body-lg font-medium text-t1">Recent papers</h2>
          <div className="flex flex-col gap-2">
            {recentPapers.map((paper) => (
              <div
                key={`${paper.paperId}-${paper.recordedAt}`}
                className="flex items-center gap-4 rounded-md border border-border bg-surface p-4"
              >
                <GradeBadge grade={paper.grade} size="inline" basis="achieved" />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <div className="text-body-lg text-t1">{paper.subjectName}</div>
                  {/* Code as secondary detail, per the §4.8 design note. */}
                  <div className="text-body-md text-t2">
                    {paper.paperId} · marked {relativeTime(paper.recordedAt)}
                  </div>
                </div>
                <div className="flex-none text-body-lg text-t1">{paper.marks}</div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <WeakTopicList topics={weakTopics} childId={childId} />
    </div>
  )
}

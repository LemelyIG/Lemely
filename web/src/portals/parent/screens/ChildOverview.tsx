/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Link, useParams } from "react-router-dom"
import { CaretRight, WarningCircle } from "@phosphor-icons/react"
import { useChildOverview } from "@/lib/hooks/useParentApi"
import { GradeBadge } from "@/components/ui/grade-badge"
import { TrendSparkline } from "@/components/ui/trend-sparkline"
import { WeaknessChip } from "@/components/ui/weakness-chip"
import { ErrorState } from "@/components/ui/state-views"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { parentLoadFailureMessage } from "@/lib/parentOutcome"
import { subjectIdentifier } from "@/lib/subjectIdentifier"
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
 * needs it — it is just not the headline, and it is set in the data face
 * (§4.2 `data-sm`), which is what that rung is for.
 *
 * ── The back link this screen used to carry ─────────────────────────────────
 * It had its own "‹ Your children" link directly beneath the shell's
 * breadcrumb row, so a parent with two children saw the same destination twice
 * in a column. The crumb is the one that stays; see `ParentTrail` in
 * `../index.tsx` for the whole finding.
 */

/** Grade ladder position is the backend's business; this screen only ever
 * renders `predictedGrade` as *predicted*. It is the same value T-03/T-05/T-06
 * render with `basis="predicted"` (P3.7 chunk d had to correct exactly this
 * inconsistency once) — the same number must not read differently on two
 * screens, and least of all across two audiences. */
function SubjectRow({ childId, subject }: { childId: string; subject: SubjectOverview }) {
  const { primary, secondary } = subjectIdentifier(
    subject.subjectName,
    subject.subjectCode,
    subject.qualificationLevel,
  )
  return (
    <Link
      to={`/parent/children/${childId}/subjects/${subject.subjectCode}`}
      className="group flex items-center gap-4 rounded-lg border border-rule bg-paper-raised p-5 transition-colors hover:border-rule-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
    >
      <GradeBadge grade={subject.predictedGrade} size="inline" basis="predicted" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="text-body-lg font-medium text-ink">{primary}</div>
        <div className="text-body-sm text-ink-muted">
          <span className="text-data-sm">{secondary}</span> ·{" "}
          {subject.paperCount === 1 ? "1 paper" : `${subject.paperCount} papers`} · latest{" "}
          <span className="text-data-sm">{Math.round(subject.latestPercentage)}%</span>
        </div>
        {/*
         * "Predicted grade against target grade" — there is no target-grade
         * column anywhere until Phase 4's onboarding questionnaire (D3.3 /
         * D3.11), so `target` is always null today. It is stated as absent
         * rather than defaulted: a defaulted target would make every child
         * look on track, which is precisely the invented precision UI spec
         * §1.4 forbids. When P4 lands, this branch starts rendering on its own.
         *
         * The absent case used to end "you can set one when goals arrive",
         * which promised a feature with no date and no route. Saying only what
         * is true today is shorter and does not have to be taken back.
         */}
        <div className="text-body-sm text-ink-faint">
          {subject.target ? `Target ${subject.target}` : "No target grade set yet."}
        </div>
      </div>
      {subject.trend.length > 1 ? (
        <TrendSparkline
          values={subject.trend.map((point) => point.percentage)}
          className="hidden flex-none sm:flex"
        />
      ) : null}
      <CaretRight
        size={16}
        className="flex-none text-ink-faint transition-transform ease-out-soft group-hover:translate-x-px"
        aria-hidden="true"
      />
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
 * `below_target` (P4.3/D4.5) gets its own phrasing too, built from
 * `BelowTargetEvidence`'s `targetGrade`/`predictedGrade`/`positionsBelow` —
 * the same evidence shape the teacher-facing `AtRiskList.tsx` translates.
 * Anything else without a hand-written parent phrasing falls back to the
 * backend's own `summary`.
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
          ? `Nothing has been submitted for ${days} days.${
              typeof lastActive === "string" ? ` The last was ${relativeTime(lastActive)}.` : ""
            }`
          : flag.summary,
    }
  }
  if (flag.reason === "below_target") {
    const target = flag.evidence.targetGrade
    const predicted = flag.evidence.predictedGrade
    const positions = flag.evidence.positionsBelow
    return {
      title: "Behind their target grade",
      body:
        typeof target === "string" && typeof predicted === "string"
          ? `Their most recent predicted grade is ${predicted}, ${
              typeof positions === "number" ? `${positions} grades` : "several grades"
            } below the ${target} target.`
          : flag.summary,
    }
  }
  return { title: "Something to look at", body: flag.summary }
}

function AtRiskPanel({ flags }: { flags: ParentAtRiskFlag[] }) {
  if (flags.length === 0) return null
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-display-md text-ink">Worth a conversation</h2>
      {flags.map((flag) => {
        const copy = atRiskCopy(flag)
        return (
          <div
            key={flag.reason}
            className="flex items-start gap-3 rounded-lg border border-rule bg-warn-wash p-5"
          >
            {/* The wash is a second signal, never the only one: the icon and
                the sentence both say this needs attention (§3.6). */}
            <WarningCircle size={20} className="mt-0.5 flex-none text-warn" aria-hidden="true" />
            <div className="flex min-w-0 flex-col gap-1">
              <div className="text-body-lg font-medium text-ink">{copy.title}</div>
              <p className="text-body-md text-ink">{copy.body}</p>
            </div>
          </div>
        )
      })}
      {/* UI spec §1.4: flags are signals, not verdicts. Said plainly, to the
          audience most likely to read one as a verdict. */}
      <p className="text-body-sm text-ink-muted">
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
        <h2 className="text-display-md text-ink">Topics they're finding hard</h2>
        <Link
          to={`/parent/children/${childId}/weaknesses`}
          // `whitespace-nowrap` and `shrink-0` (P6.1): at 320px the heading
          // beside this took enough of the row that "See all" broke into "See"
          // and "all", a two-line clickable target §6 bans. The heading is the
          // element that should absorb the squeeze here, not the control.
          // `min-w-11` too (P6.1 second pass): "See all" is 38px wide, so it
          // cleared the block axis and missed the inline one. `justify-end`
          // rather than `justify-center`, because this link sits at the end of
          // its row and centring would shift the text 3px off the edge the
          // heading beside it aligns to.
          className="shrink-0 whitespace-nowrap rounded-sm pointer-coarse:flex pointer-coarse:items-center pointer-coarse:justify-end pointer-coarse:min-h-11 pointer-coarse:min-w-11 text-body-sm text-accent-ink transition-colors hover:text-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
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
        heading="We couldn't load this"
        body={parentLoadFailureMessage(error)}
        action={{ label: "Try again", onClick: () => window.location.reload() }}
      />
    )
  }

  const { activity, subjects, recentPapers, weakTopics, atRiskFlags } = data

  return (
    <div className="flex flex-col gap-8">
      <div className="margin-rule flex flex-col gap-1">
        <h1 className="text-display-lg text-ink">{data.displayName}</h1>
        <p className="text-body-md text-ink-muted">How they're getting on, from their marked papers.</p>
      </div>

      {/* "Activity summary (how much they've been working — parents ask this
          first)." So it is first. Absence is stated as absence: a child with
          no records reads "nothing yet", never "0 days ago". */}
      <section className="flex flex-wrap gap-4">
        <div className="min-w-40 flex-1 rounded-lg border border-rule bg-paper-raised p-6">
          <div className="text-eyebrow text-ink-faint">Papers marked</div>
          {/* A count is a figure, so it is set in the data face (§4). It used
              to sit on the display rung, which is the same category error
              surface 2 found on the student's mark and grade. */}
          <div className="mt-2 text-data-lg text-ink">{activity.totalPapers}</div>
        </div>
        <div className="min-w-40 flex-1 rounded-lg border border-rule bg-paper-raised p-6">
          <div className="text-eyebrow text-ink-faint">Last worked</div>
          {/*
           * One figure, not two. This card used to print `relativeTime(...)`
           * and `daysSinceLastActivity` on consecutive lines, and the capture
           * round photographed them disagreeing: **"1d ago" directly above
           * "2 days ago"**, for one timestamp. They are two derivations of the
           * same fact — one computed in the browser from `lastActiveAt`, one
           * computed on the server by date arithmetic — so they round
           * differently across a day boundary and across timezones, and a
           * parent has no way to tell which one is the answer. This is the
           * "same label, two numbers" divergence D3.3/D3.4/D3.5 each had to
           * fix once, except visible on screen rather than across two screens.
           *
           * `relativeTime` is the one that stays: it is the phrasing the rest
           * of the product uses for a moment in the past, and it degrades
           * sensibly past a week ("2mo ago") where a day count does not.
           * `daysSinceLastActivity` is still read, but only for the fact
           * `relativeTime` cannot express, which is that today is today.
           */}
          <div className="mt-2 text-body-lg text-ink">
            {activity.lastActiveAt === null
              ? "Nothing yet"
              : activity.daysSinceLastActivity === 0
                ? "Today"
                : relativeTime(activity.lastActiveAt)}
          </div>
        </div>
      </section>

      <AtRiskPanel flags={atRiskFlags} />

      <section className="flex flex-col gap-3">
        <h2 className="text-display-md text-ink">Subjects</h2>
        {subjects.length === 0 ? (
          // Composed, not blank (§12): a line of marginalia, the explanation,
          // and what fills it. There is no action to offer here on purpose —
          // everything that fills this page is done by the child on their own
          // account, and a button for the reader to press would be a button
          // that does nothing.
          <div className="flex flex-col gap-1 rounded-lg border border-rule bg-paper-raised p-6">
            <p className="text-hand text-ink-muted">Nothing to read yet</p>
            <p className="text-body-md text-ink-muted">
              No marked papers yet. Subjects appear here once {data.displayName} has had a paper
              marked.
            </p>
          </div>
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
          <h2 className="text-display-md text-ink">Recent papers</h2>
          <div className="flex flex-col gap-2">
            {recentPapers.map((paper) => (
              <div
                key={`${paper.paperId}-${paper.recordedAt}`}
                className="flex items-center gap-4 rounded-lg border border-rule bg-paper-raised p-5"
              >
                <GradeBadge grade={paper.grade} size="inline" basis="achieved" />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <div className="text-body-lg font-medium text-ink">{paper.subjectName}</div>
                  {/* Code as secondary detail, per the §4.8 design note. */}
                  <div className="text-body-sm text-ink-muted">
                    <span className="text-data-sm">{paper.paperId}</span> · marked{" "}
                    {relativeTime(paper.recordedAt)}
                  </div>
                </div>
                {/* A mark is data, not prose (§4). */}
                <div className="flex-none text-data-md text-ink">{paper.marks}</div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <WeakTopicList topics={weakTopics} childId={childId} />
    </div>
  )
}

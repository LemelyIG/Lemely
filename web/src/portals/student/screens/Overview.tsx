/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useMemo } from "react"
import { Link } from "react-router-dom"
import { ArrowDownRight, ArrowUpRight, Minus } from "@phosphor-icons/react"
import { Card } from "@/components/ui/card"
import { Meter } from "@/components/ui/primitives"
import { buttonVariants } from "@/components/ui/button"
import { ChartFrame } from "@/components/ui/chart-frame"
import { LineChart } from "@/components/ui/lazy-chart"
import { GradeBadge } from "@/components/ui/grade-badge"
import { ErrorState } from "@/components/ui/state-views"
import { GettingStarted } from "@/components/ui/getting-started"
import { subjectToneForCode } from "@/components/ui/subject-tag"
import { toneFill } from "@/components/ui/badge"
import {
  PageHeaderSkeleton,
  ListSkeleton,
  PanelSkeleton,
} from "@/components/ui/loading-shapes"
import { cn, greetingFor } from "@/lib/utils"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
import { useOverview } from "@/lib/hooks/useStudentApi"
import type { MomentumPoint, SubjectRow } from "@/lib/studentTypes"
import { vizBg } from "../components/colors"

/*
 * Overview (isOverview) — the student dashboard. Wired to
 * `GET /student/overview` via `useOverview()`. Greeting, subjects ledger,
 * momentum line + weakest threads.
 *
 * P4.1 (redesign Phase 4, surface 1 of 10) migrated this screen to the Study
 * Notebook system. Four things changed that are not styling:
 *
 *   1. **Both panels had no empty-data state**, which DESIGN.md §11 makes
 *      mandatory on every chart. `MomentumDTO` returns no points when fewer
 *      than two grade-bearing papers exist (a line needs two) — and this
 *      screen rendered that unconditionally, producing an empty plot box with
 *      one stray dot pinned to the bottom corner and an empty label row.
 *      (At the time the DTO expressed that emptiness as `path=""`; P5.3
 *      replaced the pre-rendered SVG path with a real series.) Not exotic:
 *      it is *every* student who has just marked their first paper, i.e. the
 *      exact reader the getting-started view below hands over to. Both panels
 *      now go through `ChartFrame`, which has no children-only render path
 *      that can skip the check.
 *   2. **The trend column said "+0" in teal, with an upward reading**, for
 *      any student with one paper — `trend` is the first-to-last delta, so
 *      first *is* last and the delta is 0, while `trendUp` is `delta >= 0`
 *      and therefore true. A flat arm is derived here instead, from the
 *      number rather than from the flag.
 *   3. **The trend carried its meaning in colour alone** (teal vs red on a
 *      bare signed integer), against DESIGN.md §3.6's "colour never carries
 *      meaning alone". It is now colour plus a direction glyph plus a spoken
 *      label, and the number keeps a unit in its accessible name — a bare
 *      "+4" beside a percentage column does not say percentage *points*.
 *   4. **The "Forecast" readout was removed.** `forecast` is built as
 *      `" ".join(row.grade for row in subjects)`, so a student with three
 *      subjects read "Forecast B A C" under a label that promises one value.
 *      Every grade in that string is already rendered one row below, attached
 *      to the subject it belongs to, which is where a grade means something.
 *      The field is untouched on the DTO; only this presentation of it is
 *      gone.
 *
 * The mock's "what to study next" / "this week" agenda / IG-calculator cards
 * and the hardcoded "Papers marked"/"Hours saved" stats had no backing DTO
 * field and were removed rather than left as stale fabricated content (see
 * D1.6 finding M2).
 *
 * P5.3 (redesign Phase 5) put the momentum panel on Nivo and the shared chart
 * theme, which took the chart's geometry out of the backend. See
 * `MomentumPanel` below and `MomentumDTO`'s docstring: the transform that
 * lived in Python clipped every percentage under 55% out of its own viewbox.
 * "Weakest threads" stays as labelled meters and is logged as a §11 exception
 * — each row prints its topic and its accuracy as text, which is a stronger
 * artefact than a bar chart of six categories, and nothing about it is a plot
 * in a coordinate space.
 */

/** Where the subject ledger's trend column gets its three arms. */
function trendOf(row: SubjectRow): {
  icon: typeof ArrowUpRight
  tone: string
  /** Spoken, so the direction survives greyscale and screen readers alike. */
  spoken: string
} {
  const delta = Number(row.trend)

  // Flat is derived from the number, not from `trendUp`. The DTO sets
  // `trendUp = delta >= 0`, which folds "no change" into "improving" — and
  // "no change" is the single most common value on this screen, because a
  // student with one paper has a first-to-last delta of exactly zero.
  // `Number.isFinite` guards the case where the field stops being numeric:
  // falling back to the flag is worse than nothing only when we can do better.
  if (!Number.isFinite(delta)) {
    return row.trendUp
      ? { icon: ArrowUpRight, tone: "text-ok", spoken: "Up since your first paper" }
      : { icon: ArrowDownRight, tone: "text-err", spoken: "Down since your first paper" }
  }

  if (delta === 0) {
    return {
      icon: Minus,
      tone: "text-ink-muted",
      spoken: "No change since your first paper",
    }
  }
  return delta > 0
    ? {
        icon: ArrowUpRight,
        tone: "text-ok",
        spoken: `Up ${delta} percentage points since your first paper`,
      }
    : {
        icon: ArrowDownRight,
        tone: "text-err",
        spoken: `Down ${Math.abs(delta)} percentage points since your first paper`,
      }
}

function SubjectLedgerRow({ row }: { row: SubjectRow }) {
  const trend = trendOf(row)
  const TrendIcon = trend.icon

  return (
    <Link
      to={`/student/subject/${row.code}`}
      /*
       * A real `<Link>`, not a `<button onClick={navigate(...)}>`. This is the
       * same finding the audit raised against the teacher portal's `PaperCard`
       * (M8) sitting unremarked on the student side: a button that navigates
       * cannot be opened in a new tab, middle-clicked, copied as a link, or
       * previewed on hover, and it tells assistive technology that something
       * will happen rather than that somewhere will be reached.
       *
       * The active margin rule is the notebook's own device (§8.5) used as a
       * hover affordance — running a rule down the edge of the line you are
       * pointing at. Reserved transparent at rest so it cannot shift the row.
       */
      className={cn(
        "group flex flex-col gap-3 w-full text-start border-t border-rule px-6 py-4",
        "md:grid md:grid-subject-ledger md:items-center md:gap-4",
        "border-s-2 border-s-transparent hover:border-s-accent hover:bg-paper-sunk",
        "transition-colors duration-[var(--dur-instant)] ease-out-soft",
        "focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-focus-ring",
      )}
    >
      <div className="flex items-center gap-3 md:contents">
        {/* The syllabus code is the row's identity, and it is genuinely a
            code — mono `data-sm`, which §4.2 scopes to exactly "paper codes,
            IDs, timestamps". The pastel is §3.8's subject colouring, resolved
            from the one table allowed to decide it. */}
        <span
          className={cn(
            "inline-flex shrink-0 items-center rounded-sm px-2 py-1 text-data-sm",
            toneFill(subjectToneForCode(row.code)),
          )}
        >
          {row.code}
        </span>

        <span className="flex flex-col gap-0.5 flex-1 min-w-0 md:flex-none">
          {/* `SubjectRowDTO.name` echoes the code today, because a
              `PaperRecord` carries no human subject name. Rendering it beside
              the code chip in that case prints "0625" twice, so it appears
              only when it actually says something the chip does not. No
              client-side code-to-name table is invented to fill the gap: that
              data has an authoritative home in the backend. */}
          {row.name !== row.code ? (
            <span className="truncate text-body-md font-medium text-ink">{row.name}</span>
          ) : null}
          <span className="truncate text-body-sm text-ink-faint">{row.detail}</span>
        </span>

        <GradeBadge
          grade={row.grade}
          size="inline"
          basis="predicted"
          className="md:hidden"
        />
      </div>

      <span className="flex flex-col gap-1.5">
        <Meter
          value={row.pct}
          label={`${row.name} mastery: ${row.pct}%`}
          fillClassName={vizBg(row.barColor)}
        />
        {/* "62% · 3 papers". The separator was a spaced hyphen, which the copy
            gate's own classifier calls a dash used as punctuation (audit N1);
            a middle dot is what this is. */}
        <span className="text-data-sm text-ink-faint">
          {row.pct}% · {row.papers} {row.papers === 1 ? "paper" : "papers"}
        </span>
      </span>

      <span className={cn("flex items-center gap-1 text-data-sm", trend.tone)}>
        <TrendIcon size={14} aria-hidden="true" className="shrink-0" />
        <span aria-hidden="true">{row.trend}</span>
        <span className="sr-only">{trend.spoken}</span>
      </span>

      {/* `md:inline-flex`, not `md:block`. `GradeBadge` is an `inline-flex
          flex-col` that stacks the letter over its "Predicted" caption, and
          `display: block` overrode that — so on desktop the two ran together
          as "BPredicted" on one line while the mobile copy of the same badge
          (which gets no display override) stacked correctly. Invisible in
          source, obvious the moment the surface was photographed. */}
      <GradeBadge
        grade={row.grade}
        size="inline"
        basis="predicted"
        className="hidden md:inline-flex md:ms-auto"
      />
    </Link>
  )
}

/**
 * Momentum: percentage per corrected paper, on the shared chart theme.
 *
 * **The x-axis is the paper's position, not its date, and that is deliberate.**
 * The panel's own subtitle has always said "per corrected paper", and the chart
 * this replaces spaced points evenly by index too, so the domain here is the
 * sequence of papers rather than the calendar. It also has to be: a point scale
 * keys on its label, and the labels the wire used to carry were
 * `recorded_at[:7]` — a year-month — so a student with five papers in March
 * had five points sharing one key, which collapses into one. An ordinal is
 * unique by construction. The date is not lost; it is in every point's tooltip
 * and accessible label, which is where a date is useful and an axis of five
 * identical months never was.
 */
function MomentumPanel({ points }: { points: readonly MomentumPoint[] }) {
  const series = useMemo(
    () => [
      {
        id: "Percentage",
        data: points.map((p, i) => ({ x: String(i + 1), y: p.percentage })),
      },
    ],
    [points],
  )

  const datesByOrdinal = useMemo(() => {
    const map = new Map<string, string>()
    for (const [i, p] of points.entries()) {
      map.set(
        String(i + 1),
        new Date(p.recordedAt).toLocaleDateString(undefined, {
          year: "numeric",
          month: "short",
          day: "numeric",
        }),
      )
    }
    return map
  }, [points])

  return (
    <ChartFrame
      title="Momentum"
      subtitle="Percentage per corrected paper, all subjects"
      /*
       * `points` is empty until a second grade-bearing paper exists, because a
       * line needs two. Keying the empty state off the series itself — rather
       * than off a paper count this screen would have to recompute — means the
       * panel is empty exactly when there is nothing to draw, by construction.
       */
      isEmpty={points.length === 0}
      emptyMarginalia="One paper down"
      emptyBody="A line needs two points. Mark a second paper and your percentage over time starts drawing itself here."
      emptyAction={
        // `buttonVariants` on a `<Link>`, not a `<Button onClick>`: this
        // is a destination, and it is the convention `GettingStarted`
        // already uses for the same job. `Button` has no `asChild`.
        <Link
          to="/student/correct"
          className={buttonVariants({ variant: "secondary", size: "sm" })}
        >
          Correct another paper
        </Link>
      }
    >
      {/* `flex-1` + `justify-center`: this panel sits in a two-up row and is
          stretched to its taller sibling, so a chart pinned to the top left a
          third of the card visibly empty. Centring in the space the row gives
          it costs nothing and stops the panel reading as unfinished. */}
      <div className="flex flex-1 flex-col justify-center">
        <LineChart
          series={series}
          height={160}
          enableArea
          /*
           * Pinned 0-100, which is the substantive change P5.3 made here. The
           * hand-rolled SVG this replaces mapped 55-100% onto an 88px box, so
           * anything below 55% was drawn *past the bottom of the viewbox* (40%
           * landed at y=114) inside an element that was `overflow-visible` —
           * a struggling student's line left the chart and drew over the
           * labels beneath it. On a real axis nothing clips, and the axis
           * states the band it is showing rather than leaving it to be
           * assumed.
           */
          yMin={0}
          yMax={100}
          axisBottomLegend="Paper, oldest first"
          formatValue={(v) => `${Math.round(v)}%`}
          tooltipDetail={(point) => datesByOrdinal.get(point.x) ?? null}
          ariaLabel="Your percentage per corrected paper, oldest first"
        />
      </div>
    </ChartFrame>
  )
}

export function Overview() {
  const { data, isPending, isError, error, refetch } = useOverview()

  /*
   * P3.3: a skeleton matching this screen's real layout, replacing the single
   * line of "Loading overview…" text that used to sit here.
   *
   * The line was not merely plain, it was the wrong *size*: it occupied one
   * text row where the loaded screen renders a heading, a subjects ledger and
   * a two-up panel row, so every load ended in the page jumping several
   * hundred pixels as content arrived. That is the layout shift DESIGN.md §12
   * names (CLS < 0.1) and the reason the rule is "match the layout", not
   * "look nicer while waiting".
   */
  if (isPending) {
    return (
      <div className="lm-screen flex flex-col gap-8">
        <h1 className="sr-only">Overview</h1>
        <PageHeaderSkeleton />
        <ListSkeleton rows={3} />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <PanelSkeleton />
          <PanelSkeleton />
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="lm-screen flex flex-col gap-8">
        <h1 className="sr-only">Overview</h1>
        <ErrorState
          heading="Couldn't load your overview"
          /* P6.2, same defect as `PaperResult`: this printed `error.message`,
             so the first screen a student sees after signing in greeted a
             dropped connection with "Failed to fetch". The two screens
             redesigned first (surfaces 1 and 2) are the two the failure-copy
             family never reached, because the module that answers this
             (`studentOutcome.ts`) was not written until surface 10. */
          body={studentLoadFailureMessage(error)}
          action={{ label: "Try again", onClick: () => refetch() }}
        />
      </div>
    )
  }

  const { studentName, subjects, weakGlobal, momentum } = data

  // `studentName` is the caller's real display name (falling back to email
  // server-side), and can still be empty for an account with neither set —
  // fall back to a plain greeting rather than showing nothing.
  const greetingName = studentName || "there"

  // This read "Good afternoon" unconditionally, at every hour of the day, so
  // a student revising at eleven at night was greeted as though it were two in
  // the afternoon. A small thing, but it is the first line on the first screen
  // and it was the one sentence on the page that was plainly untrue.
  const greeting = greetingFor(new Date().getHours())

  /*
   * First run (P3.2). A student who just onboarded has no results at all yet.
   *
   * This used to be a single centred `EmptyState` — "Correct your first paper
   * to see it here" and one button. That is a correct sentence and a poor
   * first screen: it says what is missing rather than what happens next, and
   * it gives no sense of how much setting-up is left. It is replaced by the
   * composed getting-started view Phase 3.2 asks for.
   *
   * What the steps may and may not claim is constrained by what this screen
   * can actually observe. `GET /student/overview` reports subjects derived
   * from corrected papers, so `subjects.length === 0` proves exactly one
   * thing: no paper has been marked yet. It does not tell us whether this
   * student has taken a placement test, and no endpoint on this screen does.
   *
   * So no step here is marked `done`. Marking the placement step complete
   * would be a guess, and marking it `now` alongside the paper step would give
   * a first-run reader two competing primary actions. It is `later`: true,
   * useful, and not a claim about what they have already done.
   */
  if (subjects.length === 0) {
    return (
      <div className="lm-screen flex flex-col gap-8">
        <h1 className="text-display-lg text-ink">
          {greeting}, {greetingName}.
        </h1>
        <GettingStarted
          heading="Let's get your first paper marked"
          body="Lemely works from your own past papers. Mark one and this page fills in on its own."
          steps={[
            {
              title: "Correct your first paper",
              body: "Photograph or upload a paper you have already sat. Lemely finds the session and variant, pulls the official mark scheme, and marks it question by question.",
              status: "now",
              to: "/student/correct",
              actionLabel: "Correct a paper",
            },
            {
              title: "See where you stand",
              body: "Your predicted grade is measured against the real Cambridge grade boundaries for that paper, so it is a position rather than a percentage.",
              status: "later",
            },
            {
              title: "Get a study plan built from your own mistakes",
              body: "Every dropped mark is traced back to a topic. Those topics become practice questions, flashcards and a plan for the week that rewrites itself as you improve.",
              status: "later",
            },
          ]}
          footnote="Nothing here is filled in with sample data. This page stays empty until it has your own work to show."
        />
      </div>
    )
  }

  const paperCount = subjects.reduce((total, row) => total + row.papers, 0)

  return (
    <div className="lm-screen flex flex-col gap-8">
      {/* §8.5's margin rule: one hairline at the content's inline start,
          echoing the logo. It is the whole texture budget for this header —
          the Operate lane runs texture low (§13), and the paper grain on the
          portal shell is already carrying the notebook feel underneath. */}
      <header className="margin-rule flex flex-col gap-1">
        <h1 className="text-display-lg text-ink">
          {greeting}, {greetingName}.
        </h1>
        {/* Both numbers are counted from the rows on this page, so the sentence
            cannot drift from what is rendered below it. */}
        <p className="text-body-md text-ink-muted">
          {subjects.length} {subjects.length === 1 ? "subject" : "subjects"}, {paperCount}{" "}
          {paperCount === 1 ? "paper" : "papers"} corrected so far.
        </p>
      </header>

      <Card className="overflow-hidden">
        <h2 className="px-6 pt-5 pb-4 text-display-md text-ink">Subjects this session</h2>
        {subjects.map((row) => (
          <SubjectLedgerRow key={row.code} row={row} />
        ))}
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <MomentumPanel points={momentum.points} />

        <ChartFrame
          title="Weakest threads"
          subtitle="Accuracy by topic, all subjects"
          isEmpty={weakGlobal.length === 0}
          emptyMarginalia="Nothing weak yet"
          emptyBody="Topics appear here once a marked paper drops marks against them. An empty list means nothing has been traced to a topic so far, not that nothing needs work."
        >
          <div className="flex flex-col gap-3.5">
            {weakGlobal.map((thread) => (
              <div key={thread.topic} className="flex flex-col gap-1.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 truncate text-body-md text-ink">{thread.topic}</span>
                  <span className="shrink-0 text-data-sm text-ink-muted">{thread.acc}</span>
                </div>
                <Meter
                  value={thread.width}
                  label={`${thread.topic} accuracy: ${thread.acc}`}
                  fillClassName={vizBg(thread.color)}
                />
              </div>
            ))}
          </div>
        </ChartFrame>
      </div>
    </div>
  )
}

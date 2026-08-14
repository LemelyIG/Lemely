/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4 */
import { useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Button } from "@/components/ui/button"
import { Eyebrow, Meter } from "@/components/ui/primitives"
import { BarChart } from "@/components/ui/bar-chart"
import { ErrorState } from "@/components/ui/state-views"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { Celebrate, CountUp, MilestoneSticker } from "@/components/ui/celebration"
import { Fire, Snowflake } from "@phosphor-icons/react"
import { useXpProfile } from "@/lib/hooks/useXpApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import type { XpDay, XpProfile, XpSource } from "@/lib/xpTypes"

/*
 * S-31 · Profile / XP / streak (P5.8 chunk D), on chunk A's
 * `GET /api/student/xp`.
 *
 * The UI spec calls this "the training log" screen: a record of real work.
 * Which makes what is *missing* from it the most important thing to understand
 * before editing.
 *
 * **There are no lifetime stats and no achievements, and neither is a gap to
 * fill** (D5.13 §3). The spec lists "papers marked, questions answered, hours
 * studied". The obvious source for the first two is a count of `xp_events`
 * rows, and it is wrong by construction: D5.1 §3's daily caps mean a capped
 * award writes no row, and §8's dedupe means a re-corrected paper writes one
 * row for two markings. It would read as a precise lifetime count and be
 * neither precise nor a count. "Hours studied" has no source in this schema at
 * all. If this screen looks thin, that is its honest shape — a wrong number on
 * a record-of-real-work screen is worse than an absent one, because the
 * student has no way to tell.
 *
 * **The level curve is never computed here.** `levelStartXp`/`nextLevelXp` are
 * on the wire precisely so the progress bar needs no arithmetic; a second copy
 * of the curve in TypeScript would be the fifth hand-written mirror this build
 * has been burned by.
 *
 * **The streak is offered, never used as leverage.** The spec asks for a
 * streak that "feels worth protecting without being manipulative — a
 * streak-freeze that's offered kindly beats a guilt-trip". So: no countdown to
 * losing it, no red, no "don't break it now!". The freeze is stated as
 * something the student *has*.
 *
 * ── P4.4, the Study Notebook pass ────────────────────────────────────────
 *
 * This screen is where DESIGN.md §9.3's celebration register earns its keep,
 * and three things about how it is applied here are deliberate:
 *
 * 1. **The three figures are in the data face now, not the display face.**
 *    They were `font-mono text-display-sm`, which sets two competing
 *    `font-family` declarations on one element and resolves by stylesheet
 *    order rather than by intent. §4.2's `data-lg` rung *is* "the big number",
 *    it carries `tabular-nums` by construction, and it names its own face so
 *    the conflict cannot recur. Same class of defect as D4.2's `MarkDisplay`.
 *
 * 2. **A celebration fires on a value that grew while the student was
 *    watching, and at no other time.** Not on mount, not on a refresh, not on
 *    a value that fell. A count-up staged on arrival would dramatise a total
 *    the account has held since yesterday, on the one screen whose whole claim
 *    is that it measures work actually done.
 *
 * 3. **The streak milestone is a sticker, and the streak is also a plain
 *    number beside it.** §8 item 4 allows the ±2° rotation on decorative
 *    badges only; the badge here is genuinely decorative because removing it
 *    loses nothing a reader cannot get from the figure next to it.
 *
 * **Not celebrated: a leaderboard climb**, which §9.3 also names. `S-29`'s
 * wire types carry a current `rank` and no previous one, so a "you climbed"
 * flourish would have to invent the thing it is celebrating. Recorded in D4.4
 * rather than faked.
 */

/* ── Calendar ───────────────────────────────────────────────────────────── */

/**
 * Every date from `start` to `end` inclusive, as `YYYY-MM-DD`.
 *
 * Built from the window the server reports rather than assuming 28 cells, so a
 * change to the window size on the backend cannot leave this chart silently
 * mis-sized.
 */
export function calendarDays(start: string, end: string): string[] {
  const days: string[] = []
  const cursor = new Date(`${start}T00:00:00`)
  const last = new Date(`${end}T00:00:00`)
  while (cursor.getTime() <= last.getTime()) {
    const year = cursor.getFullYear()
    const month = String(cursor.getMonth() + 1).padStart(2, "0")
    const day = String(cursor.getDate()).padStart(2, "0")
    days.push(`${year}-${month}-${day}`)
    cursor.setDate(cursor.getDate() + 1)
  }
  return days
}

/**
 * XP for each day of the window, with absent days as `0`.
 *
 * **This is the one place the absent/zero collapse is correct, and it is
 * deliberate** (D5.13 §4). The backend omits days that earned nothing so that
 * "no XP" and "outside the window" cannot be confused; here the window is
 * known exactly, so an omitted day inside it means precisely zero XP. Do not
 * render the two differently — there is no third state.
 */
export function fillCalendar(profile: XpProfile): { day: string; xp: number }[] {
  const earned = new Map(profile.calendar.map((d: XpDay) => [d.day, d.xp]))
  return calendarDays(profile.calendarStart, profile.calendarEnd).map((day) => ({
    day,
    xp: earned.get(day) ?? 0,
  }))
}

/**
 * Progress into the current level, 0–100.
 *
 * Guards the denominator even though `nextLevelXp > levelStartXp` is
 * guaranteed on the wire: a NaN width silently renders an empty bar, which
 * would read as "no progress" rather than as the bug it is.
 */
export function levelProgress(profile: XpProfile): number {
  const span = profile.nextLevelXp - profile.levelStartXp
  if (span <= 0) return 0
  const into = profile.totalXp - profile.levelStartXp
  return Math.max(0, Math.min(100, (into / span) * 100))
}

const SOURCE_LABELS: Record<XpSource, string> = {
  paper_corrected: "Papers corrected",
  quiz_completed: "Quizzes",
  flashcard_reviewed: "Flashcards",
  study_session_completed: "Study sessions",
}

export function sourceLabel(source: XpSource | string): string {
  // Falls back to the raw enum value made readable rather than dropping a
  // source the backend added and this map has not caught up with — a missing
  // row would understate the week's total against the `total` printed beside
  // it.
  return (
    SOURCE_LABELS[source as XpSource] ?? source.replace(/_/g, " ")
  )
}

function formatDay(day: string): string {
  return new Date(`${day}T00:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
  })
}

/* ── Panels ─────────────────────────────────────────────────────────────── */

function LevelCard({ profile }: { profile: XpProfile }) {
  const progress = levelProgress(profile)
  const remaining = Math.max(0, profile.nextLevelXp - profile.totalXp)
  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        {/* Each label/value pair is a named `group` rather than an <Eyebrow>
            with a detached sibling <div>. The bug that fixes is real and not a
            test convenience: the number had no accessible name and no
            programmatic association with its own label, so a screen reader
            announced "Level" and "3" as two unrelated fragments.
            Deliberately NOT C-2 `MarkDisplay`'s exact shape. That one repeats
            the value inside the aria-label (`"12 out of 20 marks"`), which
            names a generic <div> — a role that has no accessible name in the
            ARIA spec — and duplicates the number into a second place that can
            drift from the first. Naming the group with the LABEL and leaving
            the value as its content associates the two with the value stated
            exactly once. */}
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div role="group" aria-label="Level">
            <Eyebrow>Level</Eyebrow>
            {/* Levelling up is the clearest achievement this screen has, so it
                takes the flourish; the XP total beside it springs without
                confetti, because two fans firing at once on one card reads as
                a slot machine rather than as two facts. */}
            <Celebrate value={profile.level} className="text-data-lg text-ink">
              <CountUp value={profile.level} />
            </Celebrate>
          </div>
          <div role="group" aria-label="Total XP" className="text-end">
            <Eyebrow>Total XP</Eyebrow>
            <Celebrate
              value={profile.totalXp}
              flourish={false}
              className="text-data-lg text-ink"
            >
              <CountUp value={profile.totalXp} />
            </Celebrate>
          </div>
        </div>
        <Meter
          value={progress}
          label={`Progress to level ${profile.level + 1}: ${Math.round(progress)}%`}
        />
        <p className="text-body-sm text-ink-faint">
          {remaining.toLocaleString()} XP to level {profile.level + 1}
        </p>
      </CardBody>
    </Card>
  )
}

function StreakCard({ profile }: { profile: XpProfile }) {
  const { current, longest, freezesAvailable, lastActiveOn } = profile.streak
  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Fire
            size={26}
            weight="fill"
            className="flex-none text-accent"
            aria-hidden="true"
          />
          {/* Label above value, matching `LevelCard`. The two cards sit side
              by side on desktop and stacked on a phone, and they had opposite
              orders: LEVEL above 7, but 21 above DAY STREAK. Three figures in
              one row of the eye's travel, two of them labelled from the top
              and one from the bottom, is a scanning cost for nothing —
              Operate mode puts consistency ahead of variety (§2). */}
          <div role="group" aria-label="Day streak">
            <Eyebrow>Day streak</Eyebrow>
            <Celebrate value={current} className="text-data-lg text-ink">
              <CountUp value={current} />
            </Celebrate>
          </div>
          {/* Decorative, and only ever alongside the figure above (§8 item 4).
              Absent below the first milestone rather than shown empty. */}
          <MilestoneSticker streakDays={current} className="ms-auto" />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Chip tone="neutral">Longest {longest}</Chip>
          {freezesAvailable > 0 ? (
            // Offered, not brandished. No countdown, no warning colour — the
            // spec asks for a freeze offered kindly rather than a guilt-trip.
            <Chip tone="accent">
              <Snowflake size={11} weight="bold" aria-hidden="true" />
              {freezesAvailable} freeze{freezesAvailable === 1 ? "" : "s"} saved
            </Chip>
          ) : null}
        </div>

        <p className="text-body-sm text-ink-faint">
          {lastActiveOn === null
            ? "Your streak starts the first day you earn XP."
            : `Last earned XP on ${formatDay(lastActiveOn)}.`}
          {freezesAvailable > 0
            ? " A freeze covers a day you miss, automatically."
            : ""}
        </p>
      </CardBody>
    </Card>
  )
}

/**
 * XP per day across the four-week window — the "XP history" chart §5.3 names.
 *
 * **This replaced a four-band intensity grid, and the reason is §3.6, not
 * fashion.** The grid was carefully built: four named bands rather than a
 * continuous ramp, a distinct empty cell, and the exact number in every cell's
 * `title` and `aria-label`. But the quantity itself still arrived in exactly
 * one visual channel — colour intensity — and every reader who degrades that
 * channel (colour vision deficiency, a phone in sunlight, greyscale printing,
 * a low-contrast display) was left with a hover tooltip as their only route to
 * a number. A bar encodes the same quantity as height, which none of those
 * degrade, and the tooltips and accessible labels carry over unchanged.
 *
 * The window's honest property survives the move and is worth restating,
 * because a bar chart could easily have lost it: a day with no XP and a day
 * the student never opened Lemely are the same zero-height bar, because they
 * are the same fact. `XpProfile.calendar` omits days that earned nothing
 * (D5.13 §4) and `fillCalendar` fills them as zero rather than as a gap —
 * treating them differently would invent a distinction the backend
 * deliberately does not make.
 */
function CalendarPanel({ profile }: { profile: XpProfile }) {
  const days = useMemo(() => fillCalendar(profile), [profile])
  const total = days.reduce((sum, d) => sum + d.xp, 0)

  const data = useMemo(
    () => days.map((d) => ({ label: formatDay(d.day), value: d.xp })),
    [days],
  )

  return (
    <div className="flex flex-col gap-3">
      <BarChart
        data={data}
        height={180}
        /*
         * A label per day is 28 ticks, which overlap into a smear on a phone
         * and are not worth reading anyway: the shape of the four weeks is the
         * point, and any specific day is one tap away in the tooltip. Every
         * seventh tick puts one label per week on the axis.
         */
        tickEvery={7}
        axisLeftLegend="XP"
        formatValue={(v) => String(Math.round(v))}
        tooltipDetail={(point) => (point.value === 0 ? "No XP earned" : null)}
        ariaLabel="XP earned per day over the last four weeks"
      />
      <p className="lm-prose text-body-sm text-ink-faint">
        {formatDay(profile.calendarStart)} – {formatDay(profile.calendarEnd)}.
        {total === 0
          ? " Nothing here yet. The first day you earn XP is the first bar on this chart."
          : " A day with no XP and a day you did not open Lemely look the same here, because they are the same thing."}
      </p>
    </div>
  )
}

function WeekPanel({ profile }: { profile: XpProfile }) {
  const { week } = profile
  const peak = Math.max(1, ...week.bySource.map((s) => s.xp))

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        {/* The figure is in the data face; the unit beside it is a word and
            stays in the body face. Surface 3 found the inverse of this — a
            whole sentence set in the mono face — and §4 gives that face
            figures, not the prose around them. */}
        <span className="text-ink">
          <Celebrate value={week.total} flourish={false} className="text-data-md">
            <CountUp value={week.total} />
          </Celebrate>
          <span className="ms-1 text-body-md text-ink-muted">XP this week</span>
        </span>
        <span className="text-body-sm text-ink-faint">
          {formatDay(week.start)} – {formatDay(week.end)}
        </span>
      </div>

      <div className="flex flex-col gap-2.5">
        {week.bySource.map((s) => (
          <div key={s.source} className="flex items-center gap-3">
            <span className="w-36 flex-none text-body-md text-ink-muted">
              {sourceLabel(s.source)}
            </span>
            <span className="min-w-0 flex-1">
              <Meter
                value={(s.xp / peak) * 100}
                label={`${sourceLabel(s.source)}: ${s.xp} XP this week`}
              />
            </span>
            {/* Labelled "XP", never bare: this is XP from a source, not a count
                of times the student did that thing (D5.13 §3). */}
            <span className="w-16 flex-none text-end text-data-md text-ink">
              {s.xp}
              <span className="ms-1 text-body-sm text-ink-faint">XP</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * The body's loading state, shaped like the body that replaces it.
 *
 * Two cards then two panels, in the grid the real content uses, because a
 * one-line "Loading your training log…" growing into four blocks moved the
 * whole page several hundred pixels — the same shift P4.2 fixed on the result
 * screen and P6.7 fixed on the board.
 */
function TrainingLogSkeleton() {
  return (
    <>
      <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
        <PanelSkeleton />
        <PanelSkeleton />
      </div>
      <PanelSkeleton />
      <PanelSkeleton />
    </>
  )
}

/* ── Screen ─────────────────────────────────────────────────────────────── */

export function Profile() {
  const navigate = useNavigate()
  const xp = useXpProfile()
  const me = useProfile()

  // `displayName` is nullable at signup, so the fallback is the email's local
  // part — a real thing about this account — rather than an invented name.
  // This is the student's own screen, so unlike the leaderboard (D5.5) there
  // is no stranger to leak an address to.
  const name =
    me.data?.displayName ?? me.data?.email.split("@")[0] ?? "Your profile"

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-1">
        <Eyebrow>Your training log</Eyebrow>
        {/* `text-display` was the class here, and it does not exist: nothing in
            index.css defines it and nothing in the shipped bundle emits it, so
            this title rendered at the browser's default h1 in the body face
            rather than at §4.2's `display-lg` in Newsreader. Third instance of
            D4.1's shape — a well-formed class name that resolves to nothing and
            is therefore invisible to every gate that looks at rendered output.
            `tests/unit/utilityExistence.test.ts` is the gate that now catches
            it. */}
        <h1 className="text-display-lg text-ink">{name}</h1>
        <p className="lm-prose text-body-lg text-ink-muted">
          Everything here measures work done, never how well you did it.
        </p>
      </header>

      {xp.isError ? (
        <ErrorState
          heading="Your XP could not be loaded"
          body="This is a connection problem. Your XP and streak are safe, and nothing has been lost."
          marginalia="Nothing you earned is lost"
          action={{ label: "Try again", onClick: () => void xp.refetch() }}
        />
      ) : xp.isPending || !xp.data ? (
        <TrainingLogSkeleton />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
            <LevelCard profile={xp.data} />
            <StreakCard profile={xp.data} />
          </div>

          <section className="flex flex-col gap-3" aria-labelledby="s31-week">
            <h2 id="s31-week" className="text-display-sm text-ink">
              This week, by source
            </h2>
            <Card>
              <CardBody>
                <WeekPanel profile={xp.data} />
              </CardBody>
            </Card>
          </section>

          <section className="flex flex-col gap-3" aria-labelledby="s31-calendar">
            <h2 id="s31-calendar" className="text-display-sm text-ink">
              The last four weeks
            </h2>
            <Card>
              <CardBody>
                <CalendarPanel profile={xp.data} />
              </CardBody>
            </Card>
          </section>
        </>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => navigate("/student/board")}
        >
          Leaderboards
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => navigate("/settings/devices")}
        >
          Your devices
        </Button>
      </div>
    </div>
  )
}

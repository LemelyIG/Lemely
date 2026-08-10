import { useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Button } from "@/components/ui/button"
import { Eyebrow, Meter } from "@/components/ui/primitives"
import { ErrorState } from "@/components/ui/state-views"
import { Fire, Snowflake } from "@phosphor-icons/react"
import { useXpProfile } from "@/lib/hooks/useXpApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import type { XpDay, XpProfile, XpSource } from "@/lib/xpTypes"
import { cn } from "@/lib/utils"

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
 */

/* ── Calendar ───────────────────────────────────────────────────────────── */

/**
 * Every date from `start` to `end` inclusive, as `YYYY-MM-DD`.
 *
 * Built from the window the server reports rather than assuming 28 cells, so a
 * change to the window size on the backend cannot leave this grid silently
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
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <Eyebrow>Level</Eyebrow>
            <div className="font-mono text-display-sm text-t1">{profile.level}</div>
          </div>
          <div className="text-right">
            <Eyebrow>Total XP</Eyebrow>
            <div className="font-mono text-display-sm text-t1">
              {profile.totalXp.toLocaleString()}
            </div>
          </div>
        </div>
        <Meter
          value={progress}
          label={`Progress to level ${profile.level + 1}: ${Math.round(progress)}%`}
        />
        <p className="text-2xs text-t3">
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
        <div className="flex items-center gap-3">
          <Fire
            size={26}
            weight="fill"
            className="flex-none text-accent"
            aria-hidden="true"
          />
          <div>
            <div className="font-mono text-display-sm text-t1">{current}</div>
            <Eyebrow>Day streak</Eyebrow>
          </div>
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

        <p className="text-2xs text-t3">
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

function CalendarPanel({ profile }: { profile: XpProfile }) {
  const days = useMemo(() => fillCalendar(profile), [profile])
  const peak = Math.max(1, ...days.map((d) => d.xp))

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1.5">
        {days.map((d) => {
          // Four bands rather than a continuous opacity ramp: a scale a reader
          // cannot name is not a scale. `xp === 0` is its own band and looks
          // like the empty cell it is.
          const intensity =
            d.xp === 0 ? 0 : d.xp >= peak * 0.66 ? 3 : d.xp >= peak * 0.33 ? 2 : 1
          return (
            <span
              key={d.day}
              // The title and the accessible label carry the number, so the
              // colour is never the only channel the value arrives on.
              title={`${formatDay(d.day)}: ${d.xp} XP`}
              role="img"
              aria-label={`${formatDay(d.day)}: ${d.xp} XP`}
              className={cn(
                "h-5 w-5 rounded-sm border",
                intensity === 0 && "border-border bg-surface-2",
                intensity === 1 && "border-accent/30 bg-accent/20",
                intensity === 2 && "border-accent/50 bg-accent/50",
                intensity === 3 && "border-accent bg-accent",
              )}
            />
          )
        })}
      </div>
      <p className="text-2xs text-t3">
        {formatDay(profile.calendarStart)} – {formatDay(profile.calendarEnd)}. A
        day with no XP and a day you did not open Lemely look the same here,
        because they are the same thing.
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
        <span className="font-mono text-body-lg text-t1">
          {week.total.toLocaleString()} XP
        </span>
        <span className="text-2xs text-t3">
          {formatDay(week.start)} – {formatDay(week.end)}
        </span>
      </div>

      <div className="flex flex-col gap-2.5">
        {week.bySource.map((s) => (
          <div key={s.source} className="flex items-center gap-3">
            <span className="w-[140px] flex-none text-dense-lg text-t2">
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
            <span className="w-16 flex-none text-right font-mono text-dense-lg text-t1">
              {s.xp}
              <span className="ml-1 text-3xs text-t3">XP</span>
            </span>
          </div>
        ))}
      </div>
    </div>
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
        <h1 className="text-display">{name}</h1>
        <p className="text-body-md text-t2">
          Everything here measures work done, never how well you did it.
        </p>
      </header>

      {xp.isError ? (
        <ErrorState
          heading="Your XP could not be loaded"
          body="This is a connection problem. Your XP and streak are safe — nothing has been lost."
          action={{ label: "Try again", onClick: () => void xp.refetch() }}
        />
      ) : xp.isPending || !xp.data ? (
        <div className="text-body-md text-t3">Loading your training log…</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
            <LevelCard profile={xp.data} />
            <StreakCard profile={xp.data} />
          </div>

          <section className="flex flex-col gap-3" aria-labelledby="s31-week">
            <h2 id="s31-week" className="text-body-lg font-medium text-t1">
              This week, by source
            </h2>
            <Card>
              <CardBody>
                <WeekPanel profile={xp.data} />
              </CardBody>
            </Card>
          </section>

          <section className="flex flex-col gap-3" aria-labelledby="s31-calendar">
            <h2 id="s31-calendar" className="text-body-lg font-medium text-t1">
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

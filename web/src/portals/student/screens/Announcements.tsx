/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState } from "@/components/ui/state-views"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Button } from "@/components/ui/button"
import {
  useAnnouncements,
  useExamCalendar,
  useMarkAnnouncementRead,
} from "@/lib/hooks/useAnnouncementApi"
import type {
  ExamDate,
  StudentAnnouncement,
  StudentExamCalendar,
  StudentExamEntry,
} from "@/lib/announcementTypes"
import { cn } from "@/lib/utils"

/*
 * S-28 · Announcements & exam calendar (P5.8 chunk B).
 *
 * Two integrated things on one screen, per the UI spec: notices from teachers
 * and school, and the official CAIE dates for the papers this student declared.
 *
 * **The calendar's empty states are the substance of this screen, not its edge
 * cases.** `exam_dates` ships empty in every environment this build produces
 * (there is no CAIE timetable on this machine — P5.5 chunk C built the
 * ingestion path and deliberately populated nothing), so in practice the
 * calendar half renders one of D5.8's three distinct "nothing here" causes
 * essentially always. They are kept apart on the wire and they are kept apart
 * here:
 *
 *   - `no_enrolment`  → the student has not told us which subjects they sit.
 *                       Fixable by them, so it gets a link to onboarding.
 *   - `no_timetable`  → they told us, and we do not hold the official dates.
 *                       Ours to fix, so it says so and offers no false action.
 *   - `no_session`    → per paper: subject declared, session not. Fixable by
 *                       them, again pointed at onboarding.
 *
 * Collapsing the first two into one blank panel would blame Cambridge for a gap
 * the student can close in thirty seconds. That is the whole reason the backend
 * models three causes instead of returning an empty list.
 *
 * **Nothing here invents a date.** The countdown counts to a real timetable
 * date or does not render; a paper with no dates says so rather than guessing
 * the session's usual month (UI spec §1.4).
 */

/* ── Dates ──────────────────────────────────────────────────────────────── */

/**
 * Whole days from today to `examDate`, both read as civil dates.
 *
 * Deliberately **not** hour-based: a student opening this at 23:00 and again at
 * 01:00 should not see "3 days" become "2 days" over one night's sleep when the
 * exam is the same calendar distance away. `startsAtLocal` is often absent
 * anyway (the timetable does not always print one), so an hour-precise
 * countdown would be precision we do not have.
 */
export function daysUntil(examDate: string, today: Date): number {
  const exam = new Date(`${examDate}T00:00:00`)
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  return Math.round((exam.getTime() - start.getTime()) / 86_400_000)
}

export function formatCountdown(days: number): string {
  if (days === 0) return "Today"
  if (days === 1) return "Tomorrow"
  return `${days} days`
}

/** Long-form date for display: "12 May 2026". */
function formatExamDate(examDate: string): string {
  return new Date(`${examDate}T00:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  })
}

/** Short-form date for display: "12 May 2026". Shared by the publish date and
 * the read receipt date — both are the same "when did this happen" fact. */
function formatDate(timestamp: string): string {
  return new Date(timestamp).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}

/**
 * The soonest exam that has not happened yet, across every declared paper.
 *
 * Returns `null` when the student holds no future dates at all — which is the
 * normal case while `exam_dates` is empty, and also the honest case for a
 * student whose series has finished. A countdown to a past date would be worse
 * than no countdown.
 */
export function nextExam(
  calendar: StudentExamCalendar | undefined,
  today: Date,
): { entry: StudentExamEntry; date: ExamDate; days: number } | null {
  if (!calendar) return null
  let best: { entry: StudentExamEntry; date: ExamDate; days: number } | null =
    null
  for (const entry of calendar.entries) {
    for (const date of entry.dates) {
      const days = daysUntil(date.examDate, today)
      if (days < 0) continue
      if (best === null || days < best.days) best = { entry, date, days }
    }
  }
  return best
}

/* ── Announcements ──────────────────────────────────────────────────────── */

/**
 * The two facts a card needs to render its read state, derived from the one
 * field the wire actually carries (`readAt`). Pulled out of the component so
 * it is a plain function a test can call without mounting anything: this is
 * the exact decision that used to be conflated with the expand toggle, so it
 * is the exact thing worth pinning on its own.
 */
export function readStateFor(announcement: {
  readAt: string | null
}): { unread: boolean; readLabel: string | null } {
  if (announcement.readAt === null) return { unread: true, readLabel: null }
  return { unread: false, readLabel: `Read on ${formatDate(announcement.readAt)}` }
}

function AnnouncementCard({
  announcement,
  isOpen,
  onToggleExpand,
  onMarkRead,
  isMarking,
  markFailed,
}: {
  announcement: StudentAnnouncement
  isOpen: boolean
  onToggleExpand: (id: string) => void
  onMarkRead: (id: string) => void
  isMarking: boolean
  markFailed: boolean
}) {
  const { unread, readLabel } = readStateFor(announcement)
  return (
    <Card
      className={cn(
        "transition-colors",
        // The unread marker is a left border rather than a bold title: a bold
        // title fights the heading hierarchy and stops being legible once three
        // in a row are unread.
        unread && "border-s-2 border-s-accent",
      )}
    >
      <CardBody className="flex flex-col gap-2">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="text-body-lg font-medium text-ink">
              {announcement.title}
            </h3>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-2xs text-ink-faint">
              <Chip tone={announcement.scope === "school" ? "accent" : "neutral"}>
                {announcement.scope === "school" ? "Whole school" : "Your class"}
              </Chip>
              <time dateTime={announcement.publishedAt}>
                {formatDate(announcement.publishedAt)}
              </time>
            </div>
          </div>
          {unread ? (
            <Chip tone="warn" className="flex-none">
              Unread
            </Chip>
          ) : (
            <p className="flex-none text-body-sm text-ink-faint">{readLabel}</p>
          )}
        </div>

        <p
          className={cn(
            "text-body-md whitespace-pre-line text-ink-muted",
            // Collapsed by default so a long notice cannot bury the ones under
            // it; the full text is one tap away and expanding still marks it
            // read, same as before — this clamp is the only reason a "show
            // more" control exists at all.
            !isOpen && "line-clamp-2",
          )}
        >
          {announcement.body}
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onToggleExpand(announcement.announcementId)}
            aria-expanded={isOpen}
            /* Every card renders a button with the identical visible text, so
               a screen-reader user tabbing a list of notices hears "Show
               more, Show more, Show more" with nothing to tell them apart.
               Naming the button with the notice it belongs to fixes that;
               the visible text stays the leading part of the accessible
               name, which is what WCAG 2.5.3 (Label in Name) requires. */
            aria-label={`${isOpen ? "Show less" : "Show more"}: ${announcement.title}`}
          >
            {isOpen ? "Show less" : "Show more"}
          </Button>
          {unread ? (
            <Button
              variant="ghost"
              size="sm"
              loading={isMarking}
              onClick={() => onMarkRead(announcement.announcementId)}
              aria-label={`${isMarking ? "Marking" : "Mark as read"}: ${announcement.title}`}
            >
              {isMarking ? "Marking…" : "Mark as read"}
            </Button>
          ) : null}
        </div>

        {markFailed ? (
          <p role="alert" className="text-body-sm text-err">
            We couldn't mark this as read. Try again.
          </p>
        ) : null}
      </CardBody>
    </Card>
  )
}

function AnnouncementsPanel() {
  const query = useAnnouncements()
  const markRead = useMarkAnnouncementRead()
  const [openId, setOpenId] = useState<string | null>(null)

  return (
    <QueryState
      query={query}
      skeleton={<ListSkeleton rows={3} />}
      error={{
        heading: "Announcements could not be loaded",
        body: "This is a connection problem on our side, not an empty noticeboard. Your teacher may well have posted something.",
      }}
      isEmpty={(data) => data.announcements.length === 0}
      empty={
        <EmptyState
          heading="No announcements yet"
          body="Notices from your teachers and your school appear here."
        />
      }
    >
      {(data) => {
        // The receipt is idempotent and stores first-read only, so calling
        // this on an already-read notice is always safe — it is what lets
        // both the explicit button and expanding-to-read share one guard
        // instead of duplicating the "already read" check at each call site.
        function handleMarkRead(id: string) {
          const announcement = data.announcements.find(
            (a) => a.announcementId === id,
          )
          if (announcement && announcement.readAt === null) markRead.mutate(id)
        }

        function handleToggleExpand(id: string) {
          setOpenId((prev) => (prev === id ? null : id))
          // Opening *is* reading: a failed receipt here must never block the
          // student from reading the text they already have in front of
          // them, which is why this is fire-and-forget rather than gating
          // the expand on the mutation settling.
          handleMarkRead(id)
        }

        return (
          <div className="flex flex-col gap-3">
            {data.announcements.map((announcement) => (
              <AnnouncementCard
                key={announcement.announcementId}
                announcement={announcement}
                isOpen={openId === announcement.announcementId}
                onToggleExpand={handleToggleExpand}
                onMarkRead={handleMarkRead}
                isMarking={
                  markRead.variables === announcement.announcementId &&
                  markRead.isPending
                }
                markFailed={
                  markRead.variables === announcement.announcementId &&
                  markRead.isError
                }
              />
            ))}
          </div>
        )
      }}
    </QueryState>
  )
}

/* ── Exam calendar ──────────────────────────────────────────────────────── */

function ExamEntryRow({ entry }: { entry: StudentExamEntry }) {
  const session =
    entry.sessionMonth && entry.sessionYear
      ? `${entry.sessionMonth} ${entry.sessionYear}`
      : null

  return (
    <div className="flex flex-col gap-2 border-b border-rule py-3 last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-body-md font-medium text-ink">
          {entry.subjectCode} Paper {entry.paperNumber}
        </span>
        {session ? (
          <span className="text-2xs text-ink-faint">{session}</span>
        ) : null}
      </div>

      {entry.availability === "dated" ? (
        <ul className="flex flex-col gap-1.5">
          {entry.dates.map((date) => (
            <li
              key={`${date.paperVariant}-${date.examDate}`}
              className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-body-md"
            >
              <span className="font-mono text-2xs text-ink-faint">
                Variant {date.paperVariant}
              </span>
              <time dateTime={date.examDate} className="text-ink">
                {formatExamDate(date.examDate)}
              </time>
              {/* Absent when the timetable prints none — never defaulted to
                  midnight, because a missing time must read as missing. */}
              {date.startsAtLocal ? (
                <span className="text-ink-muted">{date.startsAtLocal}</span>
              ) : null}
              {date.durationMinutes ? (
                <span className="text-ink-faint">{date.durationMinutes} min</span>
              ) : null}
              {/* Named on screen so a student who thinks a date is wrong can
                  cite the document rather than argue with the app. */}
              <span className="text-3xs text-ink-faint">from {date.source}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-body-md text-ink-muted">
          {entry.availability === "no_session"
            ? "You have not said which session you are sitting this paper in, so we cannot match it to a timetable."
            : "We do not hold official dates for this session yet."}
        </p>
      )}
    </div>
  )
}

function ExamCalendarPanel() {
  const navigate = useNavigate()
  const query = useExamCalendar()

  return (
    <QueryState
      query={query}
      skeleton={<ListSkeleton rows={3} />}
      error={{
        heading: "Exam dates could not be loaded",
        body: "Nothing is wrong with your timetable. This is a connection problem.",
      }}
    >
      {(data) => {
        // D5.8's two top-level causes, kept distinct, and kept inside
        // `children` rather than `isEmpty`/`empty`: that pair renders one
        // fixed node for one condition, and these are two different empty
        // causes with different content — `no_enrolment` is the student's
        // to fix and gets an action; `no_timetable` is ours and must not
        // pretend otherwise by offering one.
        if (data.availability === "no_enrolment") {
          return (
            <EmptyState
              heading="Tell us what you are sitting"
              body="Once you have added your subjects and session, the official Cambridge dates for your papers appear here."
              action={{
                label: "Finish onboarding",
                onClick: () => navigate("/student/onboard"),
              }}
            />
          )
        }

        if (data.availability === "no_timetable" || data.entries.length === 0) {
          return (
            <EmptyState
              heading="No official dates yet"
              body="We do not hold the Cambridge timetable for your session yet. Nothing is missing from your account: this one is on us, and your papers appear here as soon as we have it."
            />
          )
        }

        return (
          <div className="flex flex-col">
            {data.entries.map((entry) => (
              <ExamEntryRow
                key={`${entry.subjectCode}-${entry.paperNumber}`}
                entry={entry}
              />
            ))}
            <p className="pt-3 text-2xs text-ink-faint">
              Dates come from the official Cambridge timetable. Always check with
              your school before relying on one.
            </p>
          </div>
        )
      }}
    </QueryState>
  )
}

/* ── Countdown ──────────────────────────────────────────────────────────── */

function Countdown({ today }: { today: Date }) {
  // Deliberately not converted to `QueryState`: this component hand-rolls no
  // pending/error branch to begin with, so there is nothing here for the
  // gate to catch. It shares `useExamCalendar`'s cache with
  // `ExamCalendarPanel` (same query key, deduped by react-query), which
  // already renders that query's skeleton and error state; this component
  // quietly renders nothing until a next exam is known, on load, on error,
  // and once no future exam exists, which is unchanged.
  const { data } = useExamCalendar()
  const next = useMemo(() => nextExam(data, today), [data, today])

  // Renders nothing rather than a placeholder. "Prominent" in the UI spec means
  // prominent *when it exists*; a permanent empty hero would train the student
  // to ignore the one region that will eventually matter most.
  if (!next) return null

  return (
    // The `info` register, not the accent. Accent is this palette's alert
    // colour (recorded on surfaces 5 and 6, and this is its fourth
    // occurrence), so an exam ninety days out was painted the same as
    // something going wrong. Making it conditional on proximity was the other
    // option and was refused: any threshold for "now it is urgent" would be
    // invented, and the number in the panel already carries the urgency.
    <Card className="border-info/40 bg-info-wash">
      <CardBody className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <div>
          <Eyebrow>Your next exam</Eyebrow>
          <div className="text-display-sm text-ink">
            {formatCountdown(next.days)}
          </div>
        </div>
        <div className="text-body-md text-ink-muted">
          {next.entry.subjectCode} Paper {next.entry.paperNumber}
          <span className="text-ink-faint">
            {" "}
            · variant {next.date.paperVariant} ·{" "}
            {formatExamDate(next.date.examDate)}
            {next.date.startsAtLocal ? ` · ${next.date.startsAtLocal}` : ""}
          </span>
        </div>
      </CardBody>
    </Card>
  )
}

/* ── Screen ─────────────────────────────────────────────────────────────── */

export function Announcements() {
  // One `today` for the whole screen, so the countdown and every row agree
  // about the date even if the component re-renders across midnight.
  const today = useMemo(() => new Date(), [])

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-1">
        <Eyebrow>Announcements &amp; exams</Eyebrow>
        {/* P4.4, cross-surface: `text-display` is not a class. Nothing defines
            it and the shipped bundle emits no rule for it, so this title has
            been rendering at the browser's default h1 in the body face. The
            defect was found on the gamification screens and, per P4.2's second
            lesson, grepped for across the other portals — this is the fourth
            and last call site. `display-lg` is §4.2's in-app page title.
            The rest of this screen is still un-migrated and keeps its compat
            tokens until its own surface comes up; correcting a class that
            resolves to nothing is not a migration, it is a bug fix. */}
        <h1 className="text-display-lg text-ink">What is coming up</h1>
      </header>

      <Countdown today={today} />

      <section className="flex flex-col gap-3" aria-labelledby="s28-notices">
        <h2 id="s28-notices" className="text-body-lg font-medium text-ink">
          From your teachers
        </h2>
        <AnnouncementsPanel />
      </section>

      <section className="flex flex-col gap-3" aria-labelledby="s28-calendar">
        <h2 id="s28-calendar" className="text-body-lg font-medium text-ink">
          Exam calendar
        </h2>
        <Card>
          <CardBody>
            <ExamCalendarPanel />
          </CardBody>
        </Card>
      </section>
    </div>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — one status banner, then the three queues a tutor works through in order; links to the other tutoring screens are a ruled list, not a card grid; not yet seen in a browser. */
import { Fragment, useRef, useState, type ReactNode, type Ref } from "react"
import { Link } from "react-router-dom"
import {
  CaretRight,
  CheckCircle,
  DotsThreeCircle,
  HourglassMedium,
  LockSimple,
  PauseCircle,
  PencilSimple,
  Prohibit,
  Users,
  VideoCamera,
  WarningCircle,
  type Icon,
} from "@phosphor-icons/react"
import { Button, buttonVariants } from "@/components/ui/button"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { Modal } from "@/components/ui/modal"
import { QueryState } from "@/components/ui/query-state"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import {
  useCompleteTutorBooking,
  useDeclineTutorBooking,
  useMarkTutorBookingNoShow,
  useOwnTutorProfile,
  useTutorBookings,
} from "@/lib/hooks/useTutoringApi"
import { useOnlineStatus } from "@/lib/online"
import { isTutoringError } from "@/lib/tutoring/apiErrors"
import { listingBanner, type BannerTone, type ListingState } from "@/lib/tutoring/profileSteps"
import { formatSlotRange } from "@/lib/tutoring/slotGroups"
import {
  CANCEL_REASON_MAX,
  declineBody,
  tutorActionFailureMessage,
  tutorActions,
  tutorLoadFailureMessage,
  validateCancelReason,
} from "@/lib/tutoring/tutorSessionActions"
import type { TutorBookingsParams } from "@/lib/tutoring/queryKeys"
import { cn, relativeTime } from "@/lib/utils"
import type { Booking, TutorOwnProfile, TutoringMode } from "@/lib/tutoringTypes"

/*
 * T-15 · Tutoring home (`/teacher/tutoring`, SPEC §d).
 *
 * Top to bottom: the listing banner (what state the profile is in and the one
 * next step), then three queues, each a page of T9 filtered by effective state:
 *   - requests waiting for a reply (live pending only, soonest first, F6): Accept
 *     goes to the session page, where the meeting link or place is asked for;
 *     Decline is a small sheet with an optional reason;
 *   - upcoming accepted sessions;
 *   - sessions that have ended with no outcome (`awaiting_outcome`): Completed,
 *     or No-show behind a confirmation.
 * Every button is drawn only when the API listed that action for the booking
 * (`tutorActions`). A profile that is not yet listed or under review has no
 * sessions, so the queues are not drawn for it.
 *
 * States: loading (a skeleton of the banner and the queues), error and offline
 * (`QueryState`, per queue so one failing list does not hide the others), no
 * profile (a call to set it up), under review (the SPEC's line), empty queues
 * ("No requests yet."), and offline (buttons disabled with the reason).
 *
 * Focus: after an action the queue's heading takes focus and a status line says
 * what happened, because the row the tutor just used is gone from the list.
 */

const MODE: Record<TutoringMode, { label: string; icon: Icon }> = {
  virtual: { label: "Virtual", icon: VideoCamera },
  in_person: { label: "In person", icon: Users },
  other: { label: "Other", icon: DotsThreeCircle },
}

const BANNER_ICON: Record<string, Icon> = {
  none: PencilSimple,
  draft: PencilSimple,
  pending_review: HourglassMedium,
  listed: CheckCircle,
  paused: PauseCircle,
  rejected: WarningCircle,
  suspended: Prohibit,
  closed: LockSimple,
}

const BANNER_TONE: Record<BannerTone, { wash: string; icon: string }> = {
  ok: { wash: "bg-ok-wash", icon: "text-ok" },
  info: { wash: "bg-info-wash", icon: "text-info" },
  warn: { wash: "bg-warn-wash", icon: "text-warn" },
  neutral: { wash: "bg-paper-sunk", icon: "text-ink-muted" },
}

const SESSION_PATH = (bookingId: string) => `/teacher/tutoring/sessions/${encodeURIComponent(bookingId)}`

const SECTIONS: readonly { to: string; title: string; text: string }[] = [
  { to: "/teacher/tutoring/profile", title: "Your profile", text: "What students see, and the steps to get listed." },
  { to: "/teacher/tutoring/availability", title: "Weekly availability", text: "The hours students can book you." },
  { to: "/teacher/tutoring/preview", title: "Preview and reviews", text: "Your profile as students see it, and replies to reviews." },
  { to: "/teacher/tutoring/students", title: "My students", text: "Students who chose to share their progress with you." },
]

interface Zone {
  zone: string
  zoneLabel: string
}

// ── Banner ──────────────────────────────────────────────────────────────────

function bannerCta(state: ListingState | null): { label: string; primary: boolean } {
  switch (state) {
    case null:
      return { label: "Set up your profile", primary: true }
    case "draft":
      return { label: "Continue setup", primary: true }
    case "rejected":
      return { label: "Update your profile", primary: true }
    case "listed":
      return { label: "Edit your profile", primary: false }
    default:
      return { label: "View your profile", primary: false }
  }
}

function ListingBannerCard({ profile }: { profile: TutorOwnProfile | null }) {
  const state = profile?.listingState ?? null
  const paused = profile?.paused ?? false
  const banner = listingBanner(state, { paused, reviewNote: profile?.reviewNote ?? null })
  const key = state === null ? "none" : state === "listed" && paused ? "paused" : state
  const Glyph = BANNER_ICON[key] ?? PencilSimple
  const tone = BANNER_TONE[banner.tone]
  const cta = bannerCta(state)
  return (
    <section
      aria-labelledby="listing-status"
      className={cn("flex flex-col gap-3 rounded-lg border border-rule p-4 sm:flex-row sm:items-center", tone.wash)}
    >
      <Glyph size={24} className={cn("shrink-0", tone.icon)} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <h2 id="listing-status" className="m-0 text-display-sm text-ink">
          {banner.title}
        </h2>
        <p className="m-0 text-body-md text-ink">{banner.body}</p>
      </div>
      <Link
        to="/teacher/tutoring/profile"
        className={buttonVariants({ variant: cta.primary ? "primary" : "secondary", size: "md" })}
      >
        {cta.label}
      </Link>
    </section>
  )
}

// ── Rows and queues ─────────────────────────────────────────────────────────

function SessionFacts({ booking, zone, showRequested = false }: { booking: Booking; zone: Zone; showRequested?: boolean }) {
  const mode = MODE[booking.mode]
  const ModeIcon = mode.icon
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <Link
        to={SESSION_PATH(booking.bookingId)}
        className="text-label text-ink hover:underline"
      >
        {booking.student.displayName}
        <span className="text-ink-muted"> · {booking.subject.name}</span>
      </Link>
      <span className="text-body-sm text-ink-muted">
        {formatSlotRange(booking.startsAt, booking.endsAt, zone.zone, zone.zoneLabel)}
      </span>
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-body-sm text-ink-muted">
        <span className="inline-flex items-center gap-1">
          <ModeIcon size={14} aria-hidden />
          {mode.label}
        </span>
        {showRequested ? <span>Requested {relativeTime(booking.createdAt)}</span> : null}
      </span>
    </div>
  )
}

const ROW = "flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-4 sm:flex-row sm:items-center sm:justify-between"

interface QueueContext {
  zone: Zone
  online: boolean
  busyId: string | null
  onDecline: (booking: Booking) => void
  onComplete: (booking: Booking) => void
  onNoShow: (booking: Booking) => void
}

function RequestRow({ booking, ctx }: { booking: Booking; ctx: QueueContext }) {
  const actions = tutorActions(booking.allowedActions)
  const name = booking.student.displayName
  return (
    <li className={ROW}>
      <SessionFacts booking={booking} zone={ctx.zone} showRequested />
      <div className="flex flex-wrap gap-2">
        {actions.includes("accept") ? (
          <Link
            to={`${SESSION_PATH(booking.bookingId)}#accept`}
            className={buttonVariants({ variant: "primary", size: "sm" })}
            aria-label={`Accept the request from ${name}`}
          >
            Accept
          </Link>
        ) : null}
        {actions.includes("decline") ? (
          <Button
            variant="secondary"
            size="sm"
            disabled={!ctx.online}
            aria-label={`Decline the request from ${name}`}
            onClick={() => ctx.onDecline(booking)}
          >
            Decline
          </Button>
        ) : null}
      </div>
    </li>
  )
}

function UpcomingRow({ booking, ctx }: { booking: Booking; ctx: QueueContext }) {
  return (
    <li className={ROW}>
      <SessionFacts booking={booking} zone={ctx.zone} />
      <Link
        to={SESSION_PATH(booking.bookingId)}
        className={cn(buttonVariants({ variant: "secondary", size: "sm" }), "self-start sm:self-center")}
        aria-label={`Open the session with ${booking.student.displayName}`}
      >
        Open
        <CaretRight size={14} aria-hidden />
      </Link>
    </li>
  )
}

function OutcomeRow({ booking, ctx }: { booking: Booking; ctx: QueueContext }) {
  const actions = tutorActions(booking.allowedActions)
  const name = booking.student.displayName
  const busy = ctx.busyId === booking.bookingId
  return (
    <li className={ROW}>
      <SessionFacts booking={booking} zone={ctx.zone} />
      <div className="flex flex-wrap gap-2">
        {actions.includes("complete") ? (
          <Button
            variant="primary"
            size="sm"
            loading={busy}
            disabled={!ctx.online || (ctx.busyId !== null && !busy)}
            aria-label={`Mark the session with ${name} as completed`}
            onClick={() => ctx.onComplete(booking)}
          >
            Completed
          </Button>
        ) : null}
        {actions.includes("no_show") ? (
          <Button
            variant="secondary"
            size="sm"
            disabled={!ctx.online || ctx.busyId !== null}
            aria-label={`Mark ${name} as a no-show`}
            onClick={() => ctx.onNoShow(booking)}
          >
            No-show
          </Button>
        ) : null}
      </div>
    </li>
  )
}

function Pages({
  params,
  cursor,
  emptyText,
  row,
  ctx,
}: {
  params: TutorBookingsParams
  cursor?: string
  emptyText: string
  row: (booking: Booking, ctx: QueueContext) => ReactNode
  ctx: QueueContext
}) {
  const query = useTutorBookings(cursor === undefined ? params : { ...params, cursor })
  const [more, setMore] = useState(false)
  return (
    <QueryState
      query={query}
      skeleton={<ListSkeleton rows={2} />}
      error={{ heading: "Couldn't load these sessions", body: tutorLoadFailureMessage, compact: true }}
      isEmpty={(page) => cursor === undefined && page.items.length === 0}
      empty={<p className="m-0 text-body-md text-ink-muted">{emptyText}</p>}
    >
      {(page) => (
        <>
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {page.items.map((booking) => (
              <Fragment key={booking.bookingId}>{row(booking, ctx)}</Fragment>
            ))}
          </ul>
          {page.nextCursor ? (
            more ? (
              <Pages params={params} cursor={page.nextCursor} emptyText={emptyText} row={row} ctx={ctx} />
            ) : (
              <div>
                <Button variant="secondary" size="sm" onClick={() => setMore(true)}>
                  Show more
                </Button>
              </div>
            )
          ) : null}
        </>
      )}
    </QueryState>
  )
}

function Queue({
  id,
  title,
  lead,
  headingRef,
  children,
}: {
  id: string
  title: string
  lead?: string
  headingRef?: Ref<HTMLHeadingElement>
  children: ReactNode
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h2 id={id} ref={headingRef} tabIndex={-1} className="m-0 text-display-sm text-ink focus:outline-none">
          {title}
        </h2>
        {lead ? <p className="m-0 text-body-sm text-ink-muted">{lead}</p> : null}
      </div>
      {children}
    </section>
  )
}

// ── Decline sheet ───────────────────────────────────────────────────────────

function DeclineSheet({
  booking,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  booking: Booking | null
  pending: boolean
  error: string | null
  onCancel: () => void
  onConfirm: (reason: string) => void
}) {
  const [reason, setReason] = useState("")
  const tooLong = validateCancelReason(reason, false)
  return (
    <Modal
      open={booking !== null}
      onClose={onCancel}
      title="Decline this request?"
      description={booking ? `${booking.student.displayName}, ${booking.subject.name}` : undefined}
      dismissible={false}
      hideCloseButton
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
            Keep the request
          </Button>
          <Button
            variant="accent"
            size="sm"
            loading={pending}
            disabled={tooLong !== null}
            onClick={() => onConfirm(reason)}
          >
            Decline request
          </Button>
        </>
      }
    >
      <Textarea
        label="Reason (optional)"
        hint="The student sees that you declined. Add a reason only if it helps them."
        value={reason}
        rows={3}
        maxLength={CANCEL_REASON_MAX + 50}
        error={tooLong ?? undefined}
        onChange={(event) => setReason(event.target.value)}
      />
      {error ? (
        <p role="alert" className="mt-3 text-body-sm text-err">
          {error}
        </p>
      ) : null}
    </Modal>
  )
}

// ── The screen ──────────────────────────────────────────────────────────────

function Home({ profile }: { profile: TutorOwnProfile | null }) {
  const online = useOnlineStatus()
  const decline = useDeclineTutorBooking()
  const complete = useCompleteTutorBooking()
  const noShow = useMarkTutorBookingNoShow()
  const [declining, setDeclining] = useState<Booking | null>(null)
  const [noShowOf, setNoShowOf] = useState<Booking | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const requestsHeading = useRef<HTMLHeadingElement>(null)
  const outcomeHeading = useRef<HTMLHeadingElement>(null)

  const state = profile?.listingState ?? null
  const showSessions = profile !== null && (state === "listed" || state === "pending_review")

  const ctx: QueueContext | null = profile
    ? {
        zone: { zone: profile.zone, zoneLabel: profile.zoneLabel },
        online,
        busyId,
        onDecline: (booking) => {
          decline.reset()
          setDeclining(booking)
        },
        onComplete: (booking) => {
          setActionError(null)
          setMessage(null)
          setBusyId(booking.bookingId)
          complete
            .mutateAsync({ bookingId: booking.bookingId })
            .then(() => {
              setMessage(`Marked the session with ${booking.student.displayName} as completed.`)
              outcomeHeading.current?.focus()
            })
            .catch((error: unknown) => {
              setActionError(tutorActionFailureMessage(error, "We couldn't record that. Try again."))
            })
            .finally(() => setBusyId(null))
        },
        onNoShow: (booking) => {
          noShow.reset()
          setNoShowOf(booking)
        },
      }
    : null

  async function confirmDecline(reason: string) {
    if (!declining) return
    try {
      await decline.mutateAsync({ bookingId: declining.bookingId, body: declineBody(reason) })
      setMessage(`Declined the request from ${declining.student.displayName}.`)
      setDeclining(null)
      requestsHeading.current?.focus()
    } catch {
      // The hook keeps the error and the sheet shows it.
    }
  }

  async function confirmNoShow() {
    if (!noShowOf) return
    try {
      await noShow.mutateAsync({ bookingId: noShowOf.bookingId })
      setMessage(`Marked ${noShowOf.student.displayName} as a no-show.`)
      setNoShowOf(null)
      outcomeHeading.current?.focus()
    } catch {
      // The hook keeps the error and the dialog shows it.
    }
  }

  return (
    <div className="flex flex-col gap-6 min-w-0">
      <div className="flex flex-col gap-1 border-b border-rule pb-5">
        <h1 className="m-0 text-display-md text-ink">Tutoring</h1>
        <p className="m-0 text-body-md text-ink-muted">Your listing, the requests waiting for you and your sessions.</p>
      </div>

      <ListingBannerCard profile={profile} />

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <div className="flex flex-col gap-8 min-w-0 lg:col-span-2">
          {profile === null ? (
            <section aria-labelledby="how-it-works" className="flex flex-col gap-3">
              <h2 id="how-it-works" className="m-0 text-display-sm text-ink">
                What happens next
              </h2>
              <ol className="m-0 flex max-w-prose list-decimal flex-col gap-2 ps-5 text-body-md text-ink">
                <li>You set up your public card, add documents and choose your weekly hours.</li>
                <li>You send your profile to Lemely, who look at it and the documents.</li>
                <li>Once it is listed, students can find you and send requests, which appear on this page.</li>
              </ol>
            </section>
          ) : !showSessions ? (
            <p className="m-0 text-body-md text-ink-muted">
              {state === "suspended" || state === "closed"
                ? "Sessions and requests are not available while your profile is not listed."
                : "Requests and sessions will appear here once your profile is listed."}
            </p>
          ) : ctx ? (
            <>
              {!online ? (
                <p className="m-0 text-body-sm text-ink-muted">
                  You're offline. Replies and outcomes need a connection.
                </p>
              ) : null}
              <div aria-live="polite" className="empty:hidden">
                {message ? <p className="m-0 text-body-md text-ok">{message}</p> : null}
              </div>
              {actionError ? (
                <p role="alert" className="m-0 text-body-sm text-err">
                  {actionError}
                </p>
              ) : null}

              <Queue
                id="requests"
                title="Requests waiting for a reply"
                lead="Soonest first. A request lapses when its start time passes."
                headingRef={requestsHeading}
              >
                <Pages
                  params={{ when: "upcoming", state: "requested" }}
                  emptyText="No requests yet."
                  row={(booking, c) => <RequestRow booking={booking} ctx={c} />}
                  ctx={ctx}
                />
              </Queue>

              <Queue id="upcoming" title="Upcoming sessions">
                <Pages
                  params={{ when: "upcoming", state: "accepted" }}
                  emptyText="No sessions coming up."
                  row={(booking, c) => <UpcomingRow booking={booking} ctx={c} />}
                  ctx={ctx}
                />
              </Queue>

              <Queue
                id="outcomes"
                title="Waiting for your outcome"
                lead="These sessions have ended. Record what happened."
                headingRef={outcomeHeading}
              >
                <Pages
                  params={{ when: "past", state: "awaiting_outcome" }}
                  emptyText="Nothing is waiting for an outcome."
                  row={(booking, c) => <OutcomeRow booking={booking} ctx={c} />}
                  ctx={ctx}
                />
              </Queue>
            </>
          ) : null}
        </div>

        <nav aria-label="Tutoring sections" className="min-w-0">
          <ul className="m-0 flex list-none flex-col overflow-hidden rounded-lg border border-rule bg-paper-raised p-0">
            {SECTIONS.map((section) => (
              <li key={section.to} className="border-b border-rule last:border-b-0">
                <Link
                  to={section.to}
                  className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-paper-sunk"
                >
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="text-label text-ink">{section.title}</span>
                    <span className="text-body-sm text-ink-muted">{section.text}</span>
                  </span>
                  <CaretRight size={16} className="shrink-0 text-ink-faint" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>

      <DeclineSheet
        key={declining?.bookingId ?? "none"}
        booking={declining}
        pending={decline.isPending}
        error={tutorActionFailureMessage(decline.error, "We couldn't decline that request. Try again.")}
        onCancel={() => setDeclining(null)}
        onConfirm={(reason) => void confirmDecline(reason)}
      />

      <ConfirmModal
        open={noShowOf !== null}
        title="Mark this student as a no-show?"
        description={noShowOf ? `${noShowOf.student.displayName}, ${noShowOf.subject.name}` : undefined}
        consequence="Lemely records that the student did not come to the session. This cannot be undone."
        confirmLabel="Mark no-show"
        pendingLabel="Marking"
        cancelLabel="Keep it open"
        pending={noShow.isPending}
        error={tutorActionFailureMessage(noShow.error, "We couldn't record that. Try again.")}
        onConfirm={() => void confirmNoShow()}
        onCancel={() => setNoShowOf(null)}
      />
    </div>
  )
}

function HomeSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeaderSkeleton />
      <SkeletonBlock announce={false} className="h-20" />
      <ListSkeleton rows={3} />
    </div>
  )
}

export function TutoringHome() {
  const profileQuery = useOwnTutorProfile()
  if (isTutoringError(profileQuery.error, "no_tutor_profile")) return <Home profile={null} />
  return (
    <div className="flex flex-col gap-5 min-w-0">
      <QueryState
        query={profileQuery}
        srHeading="Tutoring"
        skeleton={<HomeSkeleton />}
        error={{ heading: "Couldn't load your tutoring page", body: tutorLoadFailureMessage }}
      >
        {(profile) => <Home profile={profile} />}
      </QueryState>
    </div>
  )
}

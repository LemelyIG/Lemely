/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — the facts first, then only the actions the API allowed, the notes thread last; the late-cancel sheet leads with the SPEC sentence and refuses a blank reason; not yet seen in a browser. */
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react"
import { Link, useLocation, useNavigate, useParams } from "react-router-dom"
import { CaretLeft, Prohibit } from "@phosphor-icons/react"
import { BookingStatus } from "@/components/ui/booking-status"
import { Button } from "@/components/ui/button"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { Input } from "@/components/ui/input"
import { PageHeaderSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import { Modal } from "@/components/ui/modal"
import { NotesThread } from "@/components/ui/notes-thread"
import { QueryState } from "@/components/ui/query-state"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { BlockSheet } from "@/components/tutoring/block-sheet"
import { ReportSheet } from "@/components/tutoring/report-sheet"
import {
  useAcceptTutorBooking,
  useCancelTutorBooking,
  useCompleteTutorBooking,
  useCreateTutoringBlock,
  useCreateTutoringReport,
  useDeclineTutorBooking,
  useMarkTutorBookingNoShow,
  useOwnTutorProfile,
  usePostTutorBookingNote,
  useTutorBooking,
  useTutorBookingNotes,
  useTutoringBlocks,
} from "@/lib/hooks/useTutoringApi"
import { useOnlineStatus } from "@/lib/online"
import { isTutoringError } from "@/lib/tutoring/apiErrors"
import { formatSlotRange } from "@/lib/tutoring/slotGroups"
import {
  ACCEPT_SERVICES,
  CANCEL_REASON_MAX,
  LATE_CANCEL_NOTICE,
  LOCATION_MAX,
  OWN_BLOCK_NOTES_LINE,
  acceptBody,
  acceptDetailFor,
  cancelBody,
  cancelRequiresReason,
  declineBody,
  meetingLinkError,
  notesFreezeView,
  requestedByLabel,
  sessionOutcomeLine,
  tutorActionFailureMessage,
  tutorActions,
  tutorLoadFailureMessage,
  validateAccept,
  validateCancelReason,
  type AcceptErrors,
} from "@/lib/tutoring/tutorSessionActions"
import type { Booking, Note, NotesPage, TutorOwnProfile, TutoringMode } from "@/lib/tutoringTypes"

/*
 * T-18 · Session detail for the tutor (`/teacher/tutoring/sessions/:bookingId`,
 * SPEC §d, rows 18 and 16).
 *
 * The facts of one booking, then the actions the API allowed for it
 * (`tutorActions` over `Booking.allowedActions`; nothing is drawn from times or
 * state), then the notes thread (C-21) and, last, the safety actions.
 *
 *   - Accept asks only for the detail the mode keeps: a meeting link for a
 *     virtual session (checked on the client against the same allowlist as the
 *     server, which stays authoritative), a place for an in-person one, nothing
 *     for "other". Opening the page at `#accept` puts the cursor in that field.
 *   - Cancel inside 24 hours (`cancel_with_reason`) opens a sheet that leads with
 *     the SPEC's sentence and will not send a blank reason; any other cancel is
 *     a plain confirmation.
 *   - "Shared progress: yes/no" comes from `studentShared`. There is no prompt to
 *     ask a student to share.
 *   - A tutor never learns that a parent link exists, so the request is always
 *     "the student's" (`requestedByLabel`).
 *   - A tutor who blocked a student also reads `notesFrozen: true` (SPEC §i.8).
 *     They know their own blocks (B1), so the thread does not claim a report is
 *     open; it says the block closed the notes.
 *
 * States: loading, error, offline, not found (through `QueryState`), every
 * effective state (the outcome sentence), no allowed actions, a frozen thread,
 * and offline (action buttons disabled with the reason).
 *
 * Focus: when the session moves to a new state the page heading takes focus,
 * because the button the tutor just used is gone.
 */

const MODE_LABEL: Record<TutoringMode, string> = {
  virtual: "Virtual",
  in_person: "In person",
  other: "Another way",
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-body-sm text-ink-muted">{label}</dt>
      <dd className="m-0 break-words text-body-md text-ink">{children}</dd>
    </div>
  )
}

const LINK = "rounded-sm text-accent-ink underline underline-offset-2 transition-colors hover:text-accent break-all"

// ── Accept ──────────────────────────────────────────────────────────────────

function AcceptPanel({
  booking,
  online,
  focusOnMount,
}: {
  booking: Booking
  online: boolean
  focusOnMount: boolean
}) {
  const accept = useAcceptTutorBooking()
  const decline = useDeclineTutorBooking()
  const detail = acceptDetailFor(booking.mode)
  const [values, setValues] = useState({ meetingLink: "", locationDetail: "" })
  const [errors, setErrors] = useState<AcceptErrors>({})
  const [declineOpen, setDeclineOpen] = useState(false)
  const [reason, setReason] = useState("")
  const fieldRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (focusOnMount) fieldRef.current?.focus()
  }, [focusOnMount])

  async function onAccept(event: FormEvent) {
    event.preventDefault()
    const found = validateAccept(booking.mode, values)
    setErrors(found)
    if (Object.keys(found).length > 0) {
      fieldRef.current?.focus()
      return
    }
    try {
      await accept.mutateAsync({ bookingId: booking.bookingId, body: acceptBody(booking.mode, values) })
    } catch {
      // Shown under the field or the button below.
    }
  }

  async function onDecline(event: FormEvent) {
    event.preventDefault()
    if (validateCancelReason(reason, false) !== null) return
    try {
      await decline.mutateAsync({ bookingId: booking.bookingId, body: declineBody(reason) })
    } catch {
      // Shown under the button below.
    }
  }

  // The server's refusals of a link or a place belong on the field they are about.
  const serverField = accept.error
    ? isTutoringError(accept.error, "meeting_link_not_allowed")
      ? ("meetingLink" as const)
      : isTutoringError(accept.error, "location_required") ||
          isTutoringError(accept.error, "contact_details_not_allowed")
        ? ("locationDetail" as const)
        : null
    : null
  const serverMessage = tutorActionFailureMessage(accept.error, "We couldn't accept that request. Try again.")
  const serviceList = `${ACCEPT_SERVICES.slice(0, -1).join(", ")} or ${ACCEPT_SERVICES.at(-1)}`

  return (
    <section id="accept" aria-labelledby="accept-title" className="flex flex-col gap-4 scroll-mt-6">
      <h2 id="accept-title" className="m-0 text-display-sm text-ink">
        Reply to this request
      </h2>

      <form onSubmit={onAccept} noValidate className="flex flex-col gap-3">
        {detail === "link" ? (
          <Input
            ref={fieldRef}
            label="Meeting link"
            type="text"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            value={values.meetingLink}
            hint={`${serviceList}. The link must start with https://.`}
            error={errors.meetingLink ?? (serverField === "meetingLink" ? serverMessage ?? undefined : undefined)}
            onBlur={() =>
              setErrors((current) => ({ ...current, meetingLink: meetingLinkError(values.meetingLink) ?? undefined }))
            }
            onChange={(event) => {
              setValues({ ...values, meetingLink: event.target.value })
              if (accept.isError) accept.reset()
            }}
          />
        ) : detail === "place" ? (
          <Input
            ref={fieldRef}
            label="Meeting place"
            autoComplete="off"
            maxLength={LOCATION_MAX}
            value={values.locationDetail}
            hint="Somewhere public is safest. Phone numbers and social handles can't go here."
            error={errors.locationDetail ?? (serverField === "locationDetail" ? serverMessage ?? undefined : undefined)}
            onChange={(event) => {
              setValues({ ...values, locationDetail: event.target.value })
              if (accept.isError) accept.reset()
            }}
          />
        ) : (
          <p className="m-0 text-body-md text-ink-muted">
            This session uses another way to meet, so there is no link or place to add.
          </p>
        )}
        {accept.isError && serverField === null ? (
          <p role="alert" className="m-0 text-body-sm text-err">
            {serverMessage}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" loading={accept.isPending} disabled={!online}>
            Accept request
          </Button>
          {!declineOpen ? (
            <Button type="button" variant="ghost" onClick={() => setDeclineOpen(true)} disabled={!online}>
              Decline instead
            </Button>
          ) : null}
        </div>
      </form>

      {declineOpen ? (
        <form onSubmit={onDecline} noValidate className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-sunk p-4">
          <Textarea
            label="Reason (optional)"
            hint="The student sees that you declined. Add a reason only if it helps them."
            rows={3}
            value={reason}
            error={validateCancelReason(reason, false) ?? undefined}
            onChange={(event) => setReason(event.target.value)}
          />
          {decline.isError ? (
            <p role="alert" className="m-0 text-body-sm text-err">
              {tutorActionFailureMessage(decline.error, "We couldn't decline that request. Try again.")}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <Button type="submit" variant="secondary" loading={decline.isPending} disabled={!online}>
              Decline request
            </Button>
            <Button type="button" variant="ghost" onClick={() => setDeclineOpen(false)} disabled={decline.isPending}>
              Keep the request
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  )
}

// ── Cancel ──────────────────────────────────────────────────────────────────

function LateCancelSheet({
  open,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  open: boolean
  pending: boolean
  error: string | null
  onCancel: () => void
  onConfirm: (reason: string) => void
}) {
  const [reason, setReason] = useState("")
  const [tried, setTried] = useState(false)
  const problem = validateCancelReason(reason, true)
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title="Cancel this session?"
      description={LATE_CANCEL_NOTICE}
      dismissible={false}
      hideCloseButton
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
            Keep the session
          </Button>
          <Button
            variant="accent"
            size="sm"
            loading={pending}
            onClick={() => {
              setTried(true)
              if (problem === null) onConfirm(reason)
            }}
          >
            Cancel session
          </Button>
        </>
      }
    >
      <Textarea
        label="Your reason"
        hint={`Required. Up to ${CANCEL_REASON_MAX} characters.`}
        rows={4}
        value={reason}
        error={tried || reason.length > CANCEL_REASON_MAX ? (problem ?? undefined) : undefined}
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

// ── Actions ─────────────────────────────────────────────────────────────────

function ActionsPanel({ booking, online }: { booking: Booking; online: boolean }) {
  const cancel = useCancelTutorBooking()
  const complete = useCompleteTutorBooking()
  const noShow = useMarkTutorBookingNoShow()
  const [sheet, setSheet] = useState<"cancel" | "no_show" | null>(null)
  const actions = tutorActions(booking.allowedActions)
  const needsReason = cancelRequiresReason(booking.allowedActions)
  const canCancel = actions.includes("cancel") || actions.includes("cancel_with_reason")
  const canComplete = actions.includes("complete")
  const canNoShow = actions.includes("no_show")
  if (!canCancel && !canComplete && !canNoShow) return null

  const busy = cancel.isPending || complete.isPending || noShow.isPending
  const failure = complete.isError
    ? tutorActionFailureMessage(complete.error, "We couldn't record that. Try again.")
    : null

  async function confirmCancel(reason: string) {
    try {
      await cancel.mutateAsync({ bookingId: booking.bookingId, body: cancelBody(reason, needsReason) })
      setSheet(null)
    } catch {
      // The sheet shows the error and stays open, with the reason kept.
    }
  }

  async function confirmNoShow() {
    try {
      await noShow.mutateAsync({ bookingId: booking.bookingId })
      setSheet(null)
    } catch {
      // The dialog shows the error.
    }
  }

  return (
    <section aria-labelledby="actions-title" className="flex flex-col gap-3">
      <h2 id="actions-title" className="m-0 text-display-sm text-ink">
        {canComplete || canNoShow ? "Record the outcome" : "Change this session"}
      </h2>
      <div className="flex flex-wrap gap-3">
        {canComplete ? (
          <Button
            variant="primary"
            loading={complete.isPending}
            disabled={!online || busy}
            onClick={() => void complete.mutateAsync({ bookingId: booking.bookingId }).catch(() => undefined)}
          >
            Completed
          </Button>
        ) : null}
        {canNoShow ? (
          <Button
            variant="secondary"
            disabled={!online || busy}
            onClick={() => {
              noShow.reset()
              setSheet("no_show")
            }}
          >
            No-show
          </Button>
        ) : null}
        {canCancel ? (
          <Button
            variant="secondary"
            disabled={!online || busy}
            onClick={() => {
              cancel.reset()
              setSheet("cancel")
            }}
          >
            Cancel session
          </Button>
        ) : null}
      </div>
      {failure ? (
        <p role="alert" className="m-0 text-body-sm text-err">
          {failure}
        </p>
      ) : null}

      {needsReason ? (
        <LateCancelSheet
          open={sheet === "cancel"}
          pending={cancel.isPending}
          error={tutorActionFailureMessage(cancel.error, "We couldn't cancel the session. Try again.")}
          onCancel={() => setSheet(null)}
          onConfirm={(reason) => void confirmCancel(reason)}
        />
      ) : (
        <ConfirmModal
          open={sheet === "cancel"}
          title="Cancel this session?"
          consequence="The student is told. This cannot be undone."
          confirmLabel="Cancel session"
          pendingLabel="Cancelling"
          cancelLabel="Keep the session"
          pending={cancel.isPending}
          error={tutorActionFailureMessage(cancel.error, "We couldn't cancel the session. Try again.")}
          onConfirm={() => void confirmCancel("")}
          onCancel={() => setSheet(null)}
        />
      )}
      <ConfirmModal
        open={sheet === "no_show"}
        title="Mark this student as a no-show?"
        consequence="Lemely records that the student did not come to the session. This cannot be undone."
        confirmLabel="Mark no-show"
        pendingLabel="Marking"
        cancelLabel="Keep it open"
        pending={noShow.isPending}
        error={tutorActionFailureMessage(noShow.error, "We couldn't record that. Try again.")}
        onConfirm={() => void confirmNoShow()}
        onCancel={() => setSheet(null)}
      />
    </section>
  )
}

// ── Notes ───────────────────────────────────────────────────────────────────

/** Fetches one further page of notes and hands it to the thread, which shows all pages as one. */
function NotesPager({
  bookingId,
  cursor,
  onLoaded,
}: {
  bookingId: string
  cursor: string
  onLoaded: (cursor: string, page: NotesPage) => void
}) {
  const query = useTutorBookingNotes(bookingId, { cursor })
  const data = query.data
  useEffect(() => {
    if (data) onLoaded(cursor, data)
  }, [data, cursor, onLoaded])
  return null
}

function SessionNotes({
  booking,
  profile,
  blockedStudentIds,
  blocksPending,
}: {
  booking: Booking
  profile: TutorOwnProfile
  blockedStudentIds: string[] | null
  blocksPending: boolean
}) {
  const first = useTutorBookingNotes(booking.bookingId)
  const post = usePostTutorBookingNote()
  const report = useCreateTutoringReport()
  const [reporting, setReporting] = useState<Note | null>(null)
  const [cursors, setCursors] = useState<string[]>([])
  const [pages, setPages] = useState<Record<string, NotesPage>>({})
  const freeze = notesFreezeView({
    notesFrozen: booking.notesFrozen,
    studentId: booking.student.studentId,
    blockedStudentIds,
  })

  const lastCursor = cursors.at(-1)
  const last = lastCursor === undefined ? first.data : pages[lastCursor]
  const hasMore = last?.nextCursor != null
  const loadingMore = lastCursor !== undefined && pages[lastCursor] === undefined

  function remember(cursor: string, page: NotesPage) {
    setPages((current) => (current[cursor] === page ? current : { ...current, [cursor]: page }))
  }

  return (
    <div className="flex flex-col gap-3">
      {/* The thread is its own labelled region ("Session notes"); this heading is not a second one. */}
      <h2 className="m-0 text-display-sm text-ink">Session notes</h2>
      <QueryState
        query={first}
        skeleton={<SkeletonBlock className="h-32" />}
        error={{ heading: "Couldn't load the notes", body: tutorLoadFailureMessage, compact: true }}
      >
        {(page) =>
          booking.notesFrozen && blocksPending ? (
            <SkeletonBlock className="h-32" />
          ) : (
            <>
              <NotesThread
                notes={[...page.items, ...cursors.flatMap((cursor) => pages[cursor]?.items ?? [])]}
                viewer="tutor"
                canPost={page.canPost}
                frozen={freeze.frozen}
                zone={profile.zone}
                zoneLabel={profile.zoneLabel}
                onPost={(body) => post.mutateAsync({ bookingId: booking.bookingId, body: { body } })}
                posting={post.isPending}
                postError={post.error}
                onReport={(note) => {
                  report.reset()
                  setReporting(note)
                }}
                hasMore={hasMore}
                loadingMore={loadingMore}
                onLoadMore={() => {
                  const next = last?.nextCursor
                  if (next) setCursors((current) => [...current, next])
                }}
                footnote={freeze.ownBlock ? OWN_BLOCK_NOTES_LINE : undefined}
              />
              {cursors.map((cursor) => (
                <NotesPager key={cursor} bookingId={booking.bookingId} cursor={cursor} onLoaded={remember} />
              ))}
            </>
          )
        }
      </QueryState>
      <ReportSheet
        open={reporting !== null}
        onClose={() => setReporting(null)}
        targetType="booking_note"
        targetLabel="this note"
        pending={report.isPending}
        error={report.error}
        sent={report.isSuccess}
        onSubmit={({ reason, details }) => {
          if (reporting) {
            report.mutate({ targetType: "booking_note", targetId: reporting.noteId, reason, details })
          }
        }}
      />
    </div>
  )
}

// ── Safety ──────────────────────────────────────────────────────────────────

function BlockStudent({ booking, alreadyBlocked }: { booking: Booking; alreadyBlocked: boolean }) {
  const block = useCreateTutoringBlock()
  const [open, setOpen] = useState(false)
  if (alreadyBlocked) {
    return (
      <p className="m-0 flex items-center gap-2 text-body-sm text-ink-muted">
        <Prohibit size={16} aria-hidden />
        You have blocked this student.
      </p>
    )
  }
  return (
    <>
      <div>
        <Button
          variant="ghost"
          size="sm"
          icon={<Prohibit size={14} />}
          onClick={() => {
            block.reset()
            setOpen(true)
          }}
        >
          Block this student
        </Button>
      </div>
      <BlockSheet
        open={open}
        viewer="tutor"
        counterpartName={booking.student.displayName}
        pending={block.isPending}
        error={block.error}
        onCancel={() => setOpen(false)}
        onConfirm={() => {
          block.mutate({ studentId: booking.student.studentId }, { onSuccess: () => setOpen(false) })
        }}
      />
    </>
  )
}

// ── Page ────────────────────────────────────────────────────────────────────

function Detail({ booking, profile }: { booking: Booking; profile: TutorOwnProfile }) {
  const online = useOnlineStatus()
  const location = useLocation()
  const blocks = useTutoringBlocks()
  const headingRef = useRef<HTMLHeadingElement>(null)
  const seenState = useRef(booking.effectiveState)

  // A new state means the button just pressed is gone: put focus on the heading.
  useEffect(() => {
    if (seenState.current === booking.effectiveState) return
    seenState.current = booking.effectiveState
    headingRef.current?.focus()
  }, [booking.effectiveState])

  const actions = tutorActions(booking.allowedActions)
  const outcome = sessionOutcomeLine(booking)
  const blockedIds = blocks.data ? blocks.data.items.map((item) => item.counterpartId) : null
  const alreadyBlocked = blockedIds?.includes(booking.student.studentId) ?? false
  const linkOk = booking.meetingLink !== null && meetingLinkError(booking.meetingLink) === null

  return (
    <div className="flex flex-col gap-6 min-w-0">
      <div className="flex flex-col gap-3 border-b border-rule pb-5">
        <Link
          to="/teacher/tutoring"
          className="inline-flex w-fit items-center gap-1 py-1 text-body-sm text-ink-muted transition-colors hover:text-ink"
        >
          <CaretLeft size={14} aria-hidden />
          Back to tutoring
        </Link>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="m-0 text-display-md text-ink focus:outline-none"
          >
            Session with {booking.student.displayName}
          </h1>
          <BookingStatus state={booking.effectiveState} />
        </div>
        {outcome ? <p className="m-0 max-w-prose text-body-md text-ink">{outcome}</p> : null}
        {!online ? (
          <p className="m-0 text-body-sm text-ink-muted">
            You're offline. Replies, cancellations and outcomes need a connection.
          </p>
        ) : null}
      </div>

      <dl className="m-0 grid max-w-3xl grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
        <Fact label="When">
          {formatSlotRange(booking.startsAt, booking.endsAt, profile.zone, profile.zoneLabel)}
        </Fact>
        <Fact label="Subject">{booking.subject.name}</Fact>
        <Fact label="Way to meet">
          {MODE_LABEL[booking.mode]}
          {booking.mode === "in_person" ? `, ${booking.area.name}` : null}
        </Fact>
        <Fact label="Requested by">{requestedByLabel(booking.requestedBy)}</Fact>
        {booking.mode === "other" && booking.otherModeNote ? (
          <Fact label="How you will meet">
            <span className="whitespace-pre-wrap">{booking.otherModeNote}</span>
          </Fact>
        ) : null}
        {booking.meetingLink ? (
          <Fact label="Meeting link">
            {linkOk ? (
              <a href={booking.meetingLink} target="_blank" rel="noopener noreferrer" className={LINK}>
                {booking.meetingLink}
              </a>
            ) : (
              <span className="break-all">{booking.meetingLink}</span>
            )}
          </Fact>
        ) : null}
        {booking.locationDetail ? (
          <Fact label="Meeting place">
            <span className="whitespace-pre-wrap">{booking.locationDetail}</span>
          </Fact>
        ) : null}
        {booking.studentShared !== null ? (
          <Fact label="Shared progress">
            {booking.studentShared ? (
              <>
                Yes.{" "}
                <Link
                  to={`/teacher/tutoring/students/${encodeURIComponent(booking.student.studentId)}`}
                  className={LINK}
                >
                  See their progress
                </Link>
              </>
            ) : (
              "No"
            )}
          </Fact>
        ) : null}
      </dl>

      {actions.includes("accept") ? (
        <AcceptPanel booking={booking} online={online} focusOnMount={location.hash === "#accept"} />
      ) : null}
      <ActionsPanel booking={booking} online={online} />

      <SessionNotes
        booking={booking}
        profile={profile}
        blockedStudentIds={blockedIds}
        blocksPending={blocks.isPending}
      />

      <div className="flex flex-col gap-2 border-t border-rule pt-5">
        <BlockStudent booking={booking} alreadyBlocked={alreadyBlocked} />
      </div>
    </div>
  )
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeaderSkeleton />
      <PanelSkeleton />
    </div>
  )
}

export function TutorSessionDetail() {
  const { bookingId = "" } = useParams()
  const navigate = useNavigate()
  const bookingQuery = useTutorBooking(bookingId)
  const profileQuery = useOwnTutorProfile()
  return (
    <div className="flex flex-col gap-5 min-w-0">
      <QueryState
        query={bookingQuery}
        srHeading="Session"
        skeleton={<DetailSkeleton />}
        error={{
          heading: "Couldn't load this session",
          body: tutorLoadFailureMessage,
          secondaryAction: { label: "Back to tutoring", onClick: () => void navigate("/teacher/tutoring") },
        }}
      >
        {(booking) => (
          <QueryState
            query={profileQuery}
            skeleton={<DetailSkeleton />}
            error={{ heading: "Couldn't load your profile", body: tutorLoadFailureMessage }}
          >
            {(profile) => <Detail key={booking.bookingId} booking={booking} profile={profile} />}
          </QueryState>
        )}
      </QueryState>
    </div>
  )
}

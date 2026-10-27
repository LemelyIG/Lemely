/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V4 — one column in reading order (what, when, where, what you can do, notes); every notice is an icon plus a sentence, and amber is kept for what needs attention. Seen in a mock-API browser harness at 320 to 1440 px, light and dark, axe clean. */
import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { ArrowSquareOut, Flag, Info, WarningCircle } from "@phosphor-icons/react"
import { BookingStatus } from "@/components/ui/booking-status"
import { Button } from "@/components/ui/button"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { NotesThread } from "@/components/ui/notes-thread"
import { SafetyNoticeSheet } from "@/components/ui/safety-notice-sheet"
import { ErrorState } from "@/components/ui/state-views"
import { TutorCard } from "@/components/ui/tutor-card"
import { ReportSheet } from "@/components/tutoring/report-sheet"
import { ReviewForm } from "@/components/tutoring/review-form"
import { useCreateTutoringReport } from "@/lib/hooks/useTutoringApi"
import { describeQueryFailure } from "@/lib/queryFailure"
import { useOnlineStatus } from "@/lib/online"
import { isTutoringError } from "@/lib/tutoring/apiErrors"
import {
  CANCEL_RULE_LINE,
  completeHint,
  COUNTING_NOTICE,
  MODE_LABEL,
  REASON_LABEL,
  SESSION_ZONE,
  SESSION_ZONE_LABEL,
  cancelSheetCopy,
  completeSheetCopy,
  insideCancelWindowNotice,
  noteNeedsSafetyNotice,
  parentNotesFootnote,
  reviewStatusLine,
  reviewView,
  sessionActionError,
  sessionActions,
  sessionPlace,
  sessionTimeLabel,
  showCountingNotice,
  stateNotice,
  type SessionViewer,
} from "@/lib/tutoring/sessionView"
import { cn } from "@/lib/utils"
import type { Booking, Note, ReviewCreate, ReviewUpdate } from "@/lib/tutoringTypes"

/*
 * S-37 Session detail, as a view that S-37 (student) and P-06 (parent) share
 * (SPEC §d). It draws one booking for one viewer; everything that needs a hook
 * for the viewer's own role (the booking, its notes, cancel, complete, review,
 * the safety notice) comes in as props, so the parent screen supplies the parent
 * hooks and leaves out what a parent does not have. Reporting is the one thing
 * both roles share, so the view owns it (R1).
 *
 *   - Controls come from `sessionActions`, which reads `allowedActions` and for a
 *     parent also who made the request. The state never turns a button on.
 *   - Inside 24 hours the view says why there is no Cancel (row 18). A tutor's
 *     late cancellation shows their reason; a cancellation by the platform shows
 *     one fixed sentence (SPEC §i.8). All of that is `lib/tutoring/sessionView.ts`.
 *   - Other people's words (a reason, a place, a meeting link) are text nodes. A
 *     meeting link becomes an anchor only when it is an http(s) address, with
 *     `rel="noopener noreferrer"`.
 *   - The notes are C-21. A student's first note waits for C-24 when the
 *     settings say the notice is unread; the draft stays in the box, and the
 *     server's 409 `safety_notice_required` brings the sheet up as well.
 *   - Offline, Cancel and Mark as completed are disabled and say why.
 *   - After a cancel or a completion the state changes under the reader; focus
 *     moves to the heading so it is not left on a control that is gone.
 */

/** The minute-grained "now" the notices compare against. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

// ── Props ───────────────────────────────────────────────────────────────────

/** A write the view can start: the screen owns the mutation. `run` must return its promise (`mutateAsync`). */
export interface SessionAction {
  run: () => Promise<unknown>
  pending: boolean
  error: unknown
  reset?: () => void
}

export interface SessionReviewActions {
  create: { run: (body: ReviewCreate) => Promise<unknown>; pending: boolean; error: unknown; reset?: () => void }
  update: {
    run: (reviewId: string, body: ReviewUpdate) => Promise<unknown>
    pending: boolean
    error: unknown
    reset?: () => void
  }
}

export interface SessionNotesInput {
  items: readonly Note[]
  /** `NotesPage.canPost` from the newest page. */
  canPost: boolean
  loading: boolean
  /** Set when the first page failed to load. */
  error: unknown
  retry: () => void
  hasMore: boolean
  loadingMore: boolean
  moreFailed: boolean
  loadMore: () => void
  /** A student's way to write a note. Omit for a parent: the thread is read-only. */
  post?: { run: (body: string) => Promise<unknown>; pending: boolean; error: unknown }
}

export interface SessionSafetyNotice {
  /** `safetyNoticeAcknowledgedAt !== null`, or null while the settings are unknown. */
  acknowledged: boolean | null
  acknowledge: SessionAction
}

export interface SessionDetailViewProps {
  booking: Booking
  viewer: SessionViewer
  /** The tutor's profile page, when the viewer can open one. */
  tutorHref?: string
  /** "Tutors & your data", the place to opt out of counting. Student only. */
  countingHref?: string
  cancel?: SessionAction
  complete?: SessionAction
  /** Student only. */
  reviews?: SessionReviewActions
  notes: SessionNotesInput
  /** Student only. */
  safetyNotice?: SessionSafetyNotice
}

// ── Pieces ──────────────────────────────────────────────────────────────────

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-4">
      <dt className="text-label text-ink-muted sm:w-32 sm:shrink-0">{label}</dt>
      <dd className="m-0 min-w-0 break-words text-body-md text-ink">{children}</dd>
    </div>
  )
}

function Notice({ tone, children }: { tone: "neutral" | "warn"; children: ReactNode }) {
  const Glyph = tone === "warn" ? WarningCircle : Info
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-md border border-rule px-3.5 py-3 text-body-md text-ink",
        tone === "warn" ? "bg-warn-wash" : "bg-paper-sunk",
      )}
    >
      <Glyph size={18} weight="bold" className={cn("mt-0.5 shrink-0", tone === "warn" ? "text-warn" : "text-ink-muted")} aria-hidden />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  )
}

/** The counting sentence with "Tutors & your data" as the link to the opt-out. */
function CountingNotice({ href }: { href: string }) {
  const label = "Tutors & your data"
  const [before, after] = COUNTING_NOTICE.split(label)
  return (
    <p className="m-0 max-w-prose text-body-sm text-ink-muted">
      {before}
      <Link to={href} className="text-accent-ink underline">
        {label}
      </Link>
      {after}
    </p>
  )
}

function ReviewArea({
  booking,
  viewer,
  nowMs,
  reviews,
}: {
  booking: Booking
  viewer: SessionViewer
  nowMs: number
  reviews?: SessionReviewActions
}) {
  const [editing, setEditing] = useState(false)
  const view = reviewView(booking, viewer, nowMs)
  if (view === null) return null

  let body: ReactNode = null
  if (view.kind === "opens" || view.kind === "unavailable") {
    body = <p className="m-0 text-body-md text-ink-muted">{view.line}</p>
  } else if (view.kind === "write" && reviews) {
    body = (
      <ReviewForm
        mode="create"
        pending={reviews.create.pending}
        error={reviews.create.error}
        onSubmit={(review) => {
          void reviews.create.run(review).catch(() => undefined)
        }}
      />
    )
  } else if (view.kind === "existing" && booking.review !== null) {
    const review = booking.review
    body = editing && reviews ? (
      <ReviewForm
        mode="edit"
        initialStars={view.stars}
        textState={view.textState}
        hasText={view.textState !== "none"}
        pending={reviews.update.pending}
        error={reviews.update.error}
        onCancel={() => setEditing(false)}
        onSubmit={(changes) => {
          void reviews.update
            .run(review.reviewId, changes)
            .then(() => setEditing(false))
            .catch(() => undefined)
        }}
      />
    ) : (
      <div className="flex flex-col gap-2">
        <p className="m-0 text-body-md text-ink">
          You rated this session {view.stars} of 5 stars. {reviewStatusLine(view.textState)}
        </p>
        {view.canEdit && reviews ? (
          <div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                reviews.update.reset?.()
                setEditing(true)
              }}
            >
              Edit review
            </Button>
          </div>
        ) : null}
      </div>
    )
  }
  if (body === null) return null
  return (
    <section aria-labelledby="session-review-heading" className="flex flex-col gap-3">
      <h2 id="session-review-heading" className="m-0 text-display-sm text-ink">
        Your review
      </h2>
      {body}
    </section>
  )
}

// ── The view ────────────────────────────────────────────────────────────────

export function SessionDetailView({
  booking,
  viewer,
  tutorHref,
  countingHref,
  cancel,
  complete,
  reviews,
  notes,
  safetyNotice,
}: SessionDetailViewProps) {
  const nowMs = useNow()
  const online = useOnlineStatus()
  const actions = sessionActions(booking, viewer)
  const notice = stateNotice(booking, viewer)
  const insideLine = insideCancelWindowNotice(booking, viewer, nowMs)
  const place = sessionPlace(booking)

  // ── Cancel and complete confirmations ──
  const [confirm, setConfirm] = useState<"cancel" | "complete" | null>(null)
  const [openConfirm, setOpenConfirm] = useState(false)
  const confirming = confirm === "cancel" ? cancel : confirm === "complete" ? complete : undefined
  const confirmCopy = confirm === "complete" ? completeSheetCopy(booking) : cancelSheetCopy(booking)

  // ── Focus follows a state change (a cancel or a completion removes its own button) ──
  // The sheet gives focus back to the button that opened it when it unmounts, and
  // that would race a heading focus made while it is still there. So a change of
  // state only marks the heading as owed; the sheet is unmounted first (its
  // focus return runs in that commit's cleanup, ahead of every effect), and the
  // heading is focused in the render after that. The heading always wins.
  const headingRef = useRef<HTMLHeadingElement>(null)
  const lastState = useRef(booking.effectiveState)
  const [headingOwed, setHeadingOwed] = useState(false)
  useEffect(() => {
    if (lastState.current === booking.effectiveState) return
    lastState.current = booking.effectiveState
    setHeadingOwed(true)
  }, [booking.effectiveState])
  useEffect(() => {
    if (!headingOwed || openConfirm) return
    if (confirm !== null) {
      setConfirm(null)
      return
    }
    headingRef.current?.focus()
    setHeadingOwed(false)
  }, [headingOwed, openConfirm, confirm])

  function ask(which: "cancel" | "complete") {
    const action = which === "cancel" ? cancel : complete
    action?.reset?.()
    setConfirm(which)
    setOpenConfirm(true)
  }

  async function confirmAction() {
    if (!confirming) return
    try {
      await confirming.run()
      setOpenConfirm(false)
    } catch {
      // The failure is on `confirming.error` and is shown inside the sheet.
    }
  }

  // ── Reporting (R1): a booking or one of its notes ──
  const report = useCreateTutoringReport()
  const [reportTarget, setReportTarget] = useState<{ type: "booking" | "booking_note"; id: string } | null>(null)
  const [reportOpen, setReportOpen] = useState(false)

  function openReport(target: { type: "booking" | "booking_note"; id: string }) {
    report.reset()
    setReportTarget(target)
    setReportOpen(true)
  }

  // ── Notes, and the safety notice that comes before a student's first one ──
  const [noticeOpen, setNoticeOpen] = useState(false)
  const post = notes.post
  const gatedPost = post
    ? async (body: string) => {
        if (safetyNotice && noteNeedsSafetyNotice(viewer, safetyNotice.acknowledged)) {
          setNoticeOpen(true)
          throw new Error("safety notice not yet read")
        }
        try {
          return await post.run(body)
        } catch (error) {
          if (safetyNotice && isTutoringError(error, "safety_notice_required")) setNoticeOpen(true)
          throw error
        }
      }
    : undefined

  async function acknowledgeNotice() {
    if (!safetyNotice) return
    try {
      await safetyNotice.acknowledge.run()
      setNoticeOpen(false)
    } catch {
      // Shown inside the sheet from `acknowledge.error`.
    }
  }

  // The thread's own `canPost` and the booking's `post_note` must both agree.
  const notesCanPost = notes.canPost && actions.postNote
  const hasActionRow = actions.cancel || actions.complete
  const offlineReason = !online && hasActionRow ? "You're offline. Reconnect to change this session." : null
  const cancelLabel = cancelSheetCopy(booking).confirmLabel

  return (
    <article className="flex w-full max-w-160 flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="m-0 min-w-0 break-words text-display-md text-ink"
          >
            {booking.subject.name} with {booking.tutor.publicName}
          </h1>
          <BookingStatus state={booking.effectiveState} />
        </div>
        <p className="m-0 text-body-md text-ink-muted">{sessionTimeLabel(booking, SESSION_ZONE, SESSION_ZONE_LABEL, nowMs)}</p>
      </header>

      {/* Announces a change of state (cancelled, completed) without moving focus again. */}
      <div aria-live="polite" className="flex flex-col gap-3 empty:hidden">
        {notice ? (
          <Notice tone={booking.cancelledLate || booking.effectiveState === "no_show" ? "warn" : "neutral"}>
            {notice.lead}
            {notice.reason !== null ? (
              <>
                {" "}
                <span className="text-label">{REASON_LABEL}</span> <span className="whitespace-pre-wrap">{notice.reason}</span>
              </>
            ) : null}
          </Notice>
        ) : null}
      </div>

      <dl className="m-0 flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-5">
        <Fact label="Format">{MODE_LABEL[booking.mode]}</Fact>
        <Fact label="Area">{booking.area.name}</Fact>
        {place ? (
          <Fact label={place.kind === "link" ? "Meeting link" : place.label}>
            {place.kind === "link" ? (
              <span className="flex flex-col gap-0.5">
                <a
                  href={place.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex w-fit items-center gap-1.5 text-accent-ink underline"
                >
                  Open the meeting link
                  <ArrowSquareOut size={14} aria-hidden />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
                <span className="text-body-sm text-ink-muted">{place.host}</span>
              </span>
            ) : (
              <span className="whitespace-pre-wrap">{place.text}</span>
            )}
          </Fact>
        ) : null}
        {booking.requestedBy === "parent" && viewer === "student" ? (
          <Fact label="Booked by">A parent booked this session for you.</Fact>
        ) : null}
      </dl>

      {hasActionRow || insideLine ? (
        <section aria-label="Actions" className="flex flex-col gap-3">
          {actions.cancel ? (
            <div className="flex flex-col gap-1.5">
              <div>
                <Button variant="secondary" size="md" disabled={!online} onClick={() => ask("cancel")}>
                  {cancelLabel}
                </Button>
              </div>
              {booking.effectiveState === "accepted" ? (
                <p className="m-0 text-body-sm text-ink-muted">{CANCEL_RULE_LINE}</p>
              ) : null}
            </div>
          ) : null}
          {insideLine ? <Notice tone="neutral">{insideLine}</Notice> : null}
          {actions.complete ? (
            <div className="flex flex-col gap-1.5">
              <div>
                <Button variant="primary" size="md" disabled={!online} onClick={() => ask("complete")}>
                  Mark as completed
                </Button>
              </div>
              <p className="m-0 max-w-prose text-body-sm text-ink-muted">{completeHint(viewer)}</p>
            </div>
          ) : null}
          {offlineReason ? <p className="m-0 text-body-sm text-ink-muted">{offlineReason}</p> : null}
        </section>
      ) : null}

      <ReviewArea key={booking.review?.reviewId ?? "none"} booking={booking} viewer={viewer} nowMs={nowMs} reviews={reviews} />

      {countingHref && showCountingNotice(booking, viewer) ? <CountingNotice href={countingHref} /> : null}

      <div className="flex flex-col gap-3">
        <h2 className="m-0 text-display-sm text-ink">
          Session notes
        </h2>
        {notes.error ? (
          <ErrorState
            compact
            heading="We couldn't load the notes"
            body={describeQueryFailure(notes.error)}
            action={{ label: "Try again", onClick: notes.retry }}
          />
        ) : (
          <>
            <NotesThread
              notes={notes.items}
              viewer={viewer}
              canPost={notesCanPost}
              frozen={booking.notesFrozen}
              zone={SESSION_ZONE}
              zoneLabel={SESSION_ZONE_LABEL}
              onPost={gatedPost}
              posting={post?.pending ?? false}
              postError={post?.error}
              onReport={(note) => openReport({ type: "booking_note", id: note.noteId })}
              loading={notes.loading}
              hasMore={notes.hasMore}
              loadingMore={notes.loadingMore}
              onLoadMore={notes.loadMore}
              footnote={viewer === "parent" ? parentNotesFootnote(booking.student.displayName) : undefined}
            />
            {notes.moreFailed ? (
              <p role="alert" className="m-0 text-body-sm text-err">
                We couldn't load more notes. Press Show more notes to try again.
              </p>
            ) : null}
          </>
        )}
      </div>

      <div className="flex justify-start border-t border-rule pt-4">
        <Button
          variant="ghost"
          size="sm"
          className="-ms-3"
          icon={<Flag size={14} />}
          onClick={() => openReport({ type: "booking", id: booking.bookingId })}
        >
          Report this session
        </Button>
      </div>

      <section aria-label="Tutor">
        <TutorCard tutor={booking.tutor} to={tutorHref} headingAs="h2" />
      </section>

      {confirming ? (
        <ConfirmModal
          open={openConfirm}
          title={confirmCopy.title}
          description={confirmCopy.description}
          consequence={confirmCopy.consequence}
          confirmLabel={confirmCopy.confirmLabel}
          pendingLabel={confirmCopy.pendingLabel}
          cancelLabel={confirmCopy.cancelLabel}
          pending={confirming.pending}
          error={sessionActionError(confirming.error, confirm === "complete" ? "complete" : "cancel")}
          onConfirm={() => void confirmAction()}
          onCancel={() => setOpenConfirm(false)}
        />
      ) : null}

      {reportTarget ? (
        <ReportSheet
          open={reportOpen}
          onClose={() => setReportOpen(false)}
          targetType={reportTarget.type}
          targetLabel={reportTarget.type === "booking" ? "this session" : "this note"}
          pending={report.isPending}
          error={report.error}
          sent={report.isSuccess}
          onSubmit={({ reason, details }) =>
            report.mutate({ targetType: reportTarget.type, targetId: reportTarget.id, reason, details })
          }
        />
      ) : null}

      {safetyNotice ? (
        <SafetyNoticeSheet
          open={noticeOpen}
          onAcknowledge={() => void acknowledgeNotice()}
          pending={safetyNotice.acknowledge.pending}
          error={safetyNotice.acknowledge.error}
        />
      ) : null}
    </article>
  )
}

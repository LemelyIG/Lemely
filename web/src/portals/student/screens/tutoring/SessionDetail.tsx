/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V4 — a thin screen that fetches and hands everything to the shared session view; loading, not-found, error and offline each have their own designed state. Seen in a mock-API browser harness at 320 to 1440 px, light and dark, axe clean. */
import { Link, useParams } from "react-router-dom"
import { ArrowLeft } from "@phosphor-icons/react"
import { buttonVariants } from "@/components/ui/button"
import { SessionDetailView } from "@/components/tutoring/session-detail-view"
import { PanelSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import {
  useAcknowledgeTutoringSafetyNotice,
  useCancelStudentBooking,
  useCompleteStudentBooking,
  useCreateReview,
  usePostStudentBookingNote,
  useStudentBooking,
  useStudentBookingNotes,
  useStudentTutoringSettings,
  useUpdateReview,
} from "@/lib/hooks/useTutoringApi"
import { describeQueryFailure } from "@/lib/queryFailure"
import { isTutoringError } from "@/lib/tutoring/apiErrors"
import { usePagedItems } from "@/lib/tutoring/sessionView"
import type { Booking, Note, NotesPage } from "@/lib/tutoringTypes"

/*
 * S-37 · Session detail (`/student/sessions/:bookingId`, SPEC §d). This screen
 * only fetches and wires: the booking (S2), its notes (S4, paged), the student's
 * tutoring settings (S12, for whether the safety notice has been read), and the
 * writes (cancel S3, complete S14, notes S5, review S6/S7, notice S15). Everything
 * the student sees is `SessionDetailView`, which P-06 shares.
 *
 * States: skeleton while the booking loads; "We couldn't find this session" for a
 * 404 (the same answer for a booking that does not exist and one that is not the
 * student's, so it is no oracle); the C-11 error and offline states with a retry;
 * the view's own states for everything about the booking itself.
 */

const noteKey = (note: Note) => note.noteId

function useNotesPage(bookingId: string, cursor: string | null) {
  return useStudentBookingNotes(bookingId, { cursor })
}

function BackToSessions() {
  return (
    <Link
      to="/student/sessions"
      className={buttonVariants({ variant: "ghost", size: "sm", className: "-ms-3 w-fit" })}
    >
      <ArrowLeft size={16} aria-hidden />
      My sessions
    </Link>
  )
}

function LoadedSession({ booking }: { booking: Booking }) {
  const bookingId = booking.bookingId
  const notes = usePagedItems<string, Note, NotesPage>(useNotesPage, bookingId, noteKey)
  const settings = useStudentTutoringSettings()
  const cancel = useCancelStudentBooking()
  const complete = useCompleteStudentBooking()
  const post = usePostStudentBookingNote()
  const createReview = useCreateReview()
  const updateReview = useUpdateReview()
  const acknowledge = useAcknowledgeTutoringSafetyNotice()

  return (
    <SessionDetailView
      booking={booking}
      viewer="student"
      tutorHref={`/student/tutors/${encodeURIComponent(booking.tutor.tutorId)}`}
      countingHref="/student/tutor-access"
      cancel={{
        run: () => cancel.mutateAsync({ bookingId }),
        pending: cancel.isPending,
        error: cancel.error,
        reset: cancel.reset,
      }}
      complete={{
        run: () => complete.mutateAsync({ bookingId }),
        pending: complete.isPending,
        error: complete.error,
        reset: complete.reset,
      }}
      reviews={{
        create: {
          run: (body) => createReview.mutateAsync({ bookingId, body }),
          pending: createReview.isPending,
          error: createReview.error,
          reset: createReview.reset,
        },
        update: {
          run: (reviewId, body) => updateReview.mutateAsync({ reviewId, body }),
          pending: updateReview.isPending,
          error: updateReview.error,
          reset: updateReview.reset,
        },
      }}
      notes={{
        items: notes.items,
        canPost: notes.page?.canPost ?? false,
        loading: notes.state.status === "pending",
        error: notes.state.status === "error" ? notes.state.error : null,
        retry: () => void notes.state.refetch(),
        hasMore: notes.hasMore,
        loadingMore: notes.loadingMore,
        moreFailed: notes.moreFailed,
        loadMore: notes.moreFailed ? notes.retryMore : notes.loadMore,
        post: {
          run: (body) => post.mutateAsync({ bookingId, body: { body } }),
          pending: post.isPending,
          error: post.error,
        },
      }}
      safetyNotice={{
        acknowledged: settings.data ? settings.data.safetyNoticeAcknowledgedAt !== null : null,
        acknowledge: {
          run: () => acknowledge.mutateAsync(),
          pending: acknowledge.isPending,
          error: acknowledge.error,
          reset: acknowledge.reset,
        },
      }}
    />
  )
}

function SessionDetailBody({ bookingId }: { bookingId: string }) {
  const booking = useStudentBooking(bookingId)
  return (
    <div className="flex w-full max-w-160 flex-col gap-4">
      <BackToSessions />
      <QueryState
        query={booking}
        srHeading="Session"
        skeleton={
          <div className="flex flex-col gap-6">
            <PageHeaderSkeleton />
            <PanelSkeleton />
          </div>
        }
        error={{
          heading: "We couldn't load this session",
          body: (error) =>
            isTutoringError(error, "not_found")
              ? "We couldn't find this session. Go back to My sessions to see yours."
              : describeQueryFailure(error),
        }}
      >
        {(data) => <LoadedSession booking={data} />}
      </QueryState>
    </div>
  )
}

export function SessionDetail() {
  const { bookingId = "" } = useParams()
  // Keyed by id: moving to another booking starts the notes paging again.
  return <SessionDetailBody key={bookingId} bookingId={bookingId} />
}

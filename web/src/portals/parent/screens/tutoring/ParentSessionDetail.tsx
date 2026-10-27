/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — a thin screen that fetches and hands everything to the shared session view; a parent reads, and acts only on what they asked for. */
import { useParams } from "react-router-dom"
import { PageHeaderSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { SessionDetailView } from "@/components/tutoring/session-detail-view"
import {
  useCancelParentChildBooking,
  useCompleteParentChildBooking,
  useParentChildBooking,
  useParentChildBookingNotes,
} from "@/lib/hooks/useTutoringApi"
import { ApiError } from "@/lib/api"
import { describeQueryFailure } from "@/lib/queryFailure"
import { isTutoringError } from "@/lib/tutoring/apiErrors"
import { parentTutorHref } from "@/lib/tutoring/parentTutoring"
import { usePagedItems } from "@/lib/tutoring/sessionView"
import type { Booking, Note, NotesPage } from "@/lib/tutoringTypes"
import { ChildScope } from "./ChildTutoring"

/*
 * P-06 · Session detail, read-only (`/parent/children/:childId/sessions/:bookingId`,
 * SPEC §d). The same facts as S-37, drawn by the shared `SessionDetailView` with
 * `viewer="parent"`: the meeting place after accept, a tutor's late-cancel
 * reason, the notes as C-21 with no composer ("Notes are between {child} and the
 * tutor..."), and Report. Cancel and Mark as completed appear only when this
 * parent made the request and the API lists the action (`sessionActions`), so a
 * session the child booked is read-only here.
 *
 * What a parent does not get, by leaving it out of the props: a review form, the
 * safety notice (C-24; the child sees it before their first note), the
 * counting-opt-out link, and any way to post a note.
 *
 * No back link of its own: the shell's trail (Overview, Tutoring, Session) is the
 * way back to P-05, and a second one pointing the same way is the duplicate the
 * parent shell removed in P4.6 (`ParentTrail` in `../../index.tsx`).
 *
 * The child is the one on the linked list (`ChildScope`); the booking and its
 * notes are asked for under that child, so a booking of another child is a 404
 * here. A 404 reads "We couldn't find this session": the same words for a
 * missing booking and one that is not this child's.
 */

const noteKey = (note: Note) => note.noteId

interface NotesScope {
  childId: string
  bookingId: string
}

function useNotesPage(scope: NotesScope, cursor: string | null) {
  return useParentChildBookingNotes(scope.childId, scope.bookingId, { cursor })
}

function LoadedSession({ childId, booking }: { childId: string; booking: Booking }) {
  const bookingId = booking.bookingId
  const notes = usePagedItems<NotesScope, Note, NotesPage>(useNotesPage, { childId, bookingId }, noteKey)
  const cancel = useCancelParentChildBooking()
  const complete = useCompleteParentChildBooking()

  return (
    <SessionDetailView
      booking={booking}
      viewer="parent"
      tutorHref={parentTutorHref(booking.tutor.tutorId)}
      cancel={{
        run: () => cancel.mutateAsync({ childId, bookingId }),
        pending: cancel.isPending,
        error: cancel.error,
        reset: cancel.reset,
      }}
      complete={{
        run: () => complete.mutateAsync({ childId, bookingId }),
        pending: complete.isPending,
        error: complete.error,
        reset: complete.reset,
      }}
      notes={{
        items: notes.items,
        canPost: false,
        loading: notes.state.status === "pending",
        error: notes.state.status === "error" ? notes.state.error : null,
        retry: () => void notes.state.refetch(),
        hasMore: notes.hasMore,
        loadingMore: notes.loadingMore,
        moreFailed: notes.moreFailed,
        loadMore: notes.moreFailed ? notes.retryMore : notes.loadMore,
      }}
    />
  )
}

function SessionBody({ childId, childName, bookingId }: { childId: string; childName: string; bookingId: string }) {
  const booking = useParentChildBooking(childId, bookingId)
  return (
    <div className="flex w-full max-w-160 flex-col gap-4">
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
            (error instanceof ApiError && error.status === 404) || isTutoringError(error, "not_found")
              ? `We couldn't find this session. Go back to ${childName}'s tutoring to see theirs.`
              : describeQueryFailure(error),
        }}
      >
        {(data) => <LoadedSession childId={childId} booking={data} />}
      </QueryState>
    </div>
  )
}

export function ParentSessionDetail() {
  const { childId = "", bookingId = "" } = useParams()
  return (
    <ChildScope key={`${childId}/${bookingId}`} childId={childId} srHeading="Session">
      {(child) => <SessionBody childId={child.childId} childName={child.displayName} bookingId={bookingId} />}
    </ChildScope>
  )
}

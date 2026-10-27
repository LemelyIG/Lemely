/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — the notice comes first and cannot be skipped, then one plain form; nothing here is styled to make a booking feel lighter than it is. */
import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { QueryState } from "@/components/ui/query-state"
import { SafetyNoticeSheet } from "@/components/ui/safety-notice-sheet"
import { BookingForm } from "@/components/tutoring/booking-form"
import { TutorFailure, TutorProfileSkeleton } from "@/components/tutoring/tutor-profile-view"
import {
  useAcknowledgeTutoringSafetyNotice,
  useStudentTutoringSettings,
  useTutorProfile,
} from "@/lib/hooks/useTutoringApi"
import { bookingRefusalOf } from "@/lib/tutoring/bookingErrors"
import type { TutorProfile } from "@/lib/tutoringTypes"

/*
 * S-35 · Book a session (`/student/tutors/:tutorId/book`, SPEC §d). The safety
 * notice (C-24) is shown first, before the form is usable, whenever the student
 * has not acknowledged it (`safetyNoticeAcknowledgedAt` is null on S12); its
 * button calls S15 and the sheet closes when the settings answer arrives. The
 * server enforces the rule (O26): if it still answers `safety_notice_required`
 * (the notice was read on another device a moment ago, or the settings read was
 * stale) the sheet opens again, so a request is never lost to it.
 *
 * The sheet has a "Not now" beside the button: it goes back to the tutor's profile
 * without acknowledging (replacing this page, so Back does not return to the
 * sheet). Booking still needs the acknowledgement; the 409 gate is unchanged.
 * The sheet's documents sentence follows the tutor's `documentsSeen`.
 *
 * If the settings cannot be read the form is still shown, and the server's
 * answer is the backstop. The form itself is `BookingForm`; a request that goes
 * through lands on S-37 (`/student/sessions/:bookingId`).
 */

function Booking({ tutor }: { tutor: TutorProfile }) {
  const navigate = useNavigate()
  const settings = useStudentTutoringSettings()
  const acknowledge = useAcknowledgeTutoringSafetyNotice()
  const [serverWantsNotice, setServerWantsNotice] = useState(false)

  if (settings.isPending) return <TutorProfileSkeleton />
  const needsNotice = serverWantsNotice || settings.data?.safetyNoticeAcknowledgedAt === null

  return (
    <div className="flex w-full max-w-160 flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="m-0 text-display-md text-ink">Book a session with {tutor.publicName}</h1>
        <p className="m-0 text-body-md text-ink-muted">
          <Link to={`/student/tutors/${tutor.tutorId}`} className="underline underline-offset-4">
            Back to their profile
          </Link>
        </p>
      </div>
      <BookingForm
        audience="student"
        tutor={tutor}
        sessionsPath="/student/sessions"
        directoryPath="/student/tutors"
        bookedPath={(booking) => `/student/sessions/${booking.bookingId}`}
        onSafetyNoticeRequired={() => setServerWantsNotice(true)}
        safetyNoticeOpen={needsNotice}
      />
      <SafetyNoticeSheet
        open={needsNotice}
        pending={acknowledge.isPending}
        error={acknowledge.error}
        onAcknowledge={() => acknowledge.mutate(undefined, { onSuccess: () => setServerWantsNotice(false) })}
        onNotNow={() => navigate(`/student/tutors/${tutor.tutorId}`, { replace: true })}
        documentsSeen={tutor.documentsSeen}
      />
    </div>
  )
}

export function BookSession() {
  const { tutorId = "" } = useParams()
  const profile = useTutorProfile(tutorId)
  const navigate = useNavigate()

  if (profile.isError && bookingRefusalOf(profile.error) !== null) {
    return (
      <TutorFailure error={profile.error} onRetry={() => void profile.refetch()} directoryPath="/student/tutors" />
    )
  }

  return (
    <QueryState
      query={profile}
      skeleton={<TutorProfileSkeleton />}
      srHeading="Book a session"
      error={{
        heading: "We couldn't load this tutor",
        retryLabel: "Try again",
        secondaryAction: { label: "Find a tutor", onClick: () => navigate("/student/tutors") },
      }}
    >
      {(tutor) => <Booking tutor={tutor} />}
    </QueryState>
  )
}

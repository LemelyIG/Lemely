/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — the student's three discovery screens in the parent's shell, with one extra decision made visible and required: which child the request is for. */
import { useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { ArrowLeft } from "@phosphor-icons/react"
import { BookingForm } from "@/components/tutoring/booking-form"
import { DirectoryView } from "@/components/tutoring/directory-view"
import { ReportSheet } from "@/components/tutoring/report-sheet"
import {
  ReviewsSection,
  TutorFailure,
  TutorOutcomes,
  TutorProfileSkeleton,
  TutorProfileView,
} from "@/components/tutoring/tutor-profile-view"
import { Button, buttonVariants } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Select } from "@/components/ui/select"
import { EmptyState } from "@/components/ui/state-views"
import { useChildren } from "@/lib/hooks/useParentApi"
import { useCreateTutoringReport, useTutorProfile } from "@/lib/hooks/useTutoringApi"
import { parentLoadFailureMessage } from "@/lib/parentOutcome"
import type { ChildSummary } from "@/lib/parentTypes"
import { bookingRefusalOf } from "@/lib/tutoring/bookingErrors"
import {
  DIRECTORY_INTRO,
  GRADE_RANKING_NOTE,
  filtersFromSearchParams,
  filtersToSearchParams,
  type DirectoryFilterState,
} from "@/lib/tutoring/discovery"
import {
  PARENT_TUTORS_PATH,
  parentBookHref,
  parentChildTutoringHref,
  parentDirectoryHref,
  parentSessionHref,
  parentTutorHref,
  preselectedChild,
  resolveLinkedChild,
} from "@/lib/tutoring/parentTutoring"
import { cn } from "@/lib/utils"
import type { TutorProfile } from "@/lib/tutoringTypes"

/*
 * P-07 · Find a tutor (parent) (`/parent/tutors`, `/parent/tutors/:tutorId`,
 * `/parent/tutors/:tutorId/book`, SPEC §d). S-33, S-34 and S-35 in the parent
 * shell, with these differences:
 *
 *   - The booking step has a required "Booking for" selector. Its options are
 *     the parent's LINKED children (`GET /parent/children`), never typed text,
 *     so SP6 can only be sent for a child the parent can book for. That matters
 *     because SP6 answers 404 for a hidden tutor and for an unknown child with
 *     the same body: with the child taken from the list, a 404 can only mean the
 *     tutor, and it reads as the one generic answer ("This tutor isn't taking
 *     bookings right now."), which never mentions a block.
 *   - `?child=` (from P-05's "Find a tutor for {child}") only preselects: it
 *     is used when that child is on the linked list, and a parent with one child
 *     gets that child. Anything else leaves the choice to the parent.
 *   - No first-note field (F19: only the student may write one), a counting
 *     notice phrased for the child, and none of "Share my progress", Block or the
 *     safety notice (C-24). Report stays.
 *   - A parent with no linked child sees how to link one instead of the form.
 *
 * A request that goes through lands on P-06 for the booking's own student.
 */

// ── The directory ──────────────────────────────────────────────────────────

export function ParentFindTutor() {
  const [params, setParams] = useSearchParams()
  const childParam = params.get("child")
  const filters = filtersFromSearchParams(params, "member")
  const children = useChildren()
  const child = children.data && childParam ? resolveLinkedChild(children.data.children, childParam) : null

  const change = (next: DirectoryFilterState) => {
    const nextParams = filtersToSearchParams(next, "member")
    // The child rides along in the address; a filter change must not drop it.
    if (childParam) nextParams.set("child", childParam)
    setParams(nextParams, { replace: true })
  }

  return (
    <div className="flex w-full flex-col gap-6 pt-4">
      <div className="flex flex-col gap-2">
        <h1 className="m-0 text-display-md text-ink">Tutors</h1>
        <p className="m-0 max-w-prose text-body-md text-ink-muted">{DIRECTORY_INTRO}</p>
        {child ? (
          <p className="m-0 max-w-prose text-body-md text-ink">
            Looking for a tutor for {child.displayName}.{" "}
            <Link to={parentChildTutoringHref(child.childId)} className="text-accent-ink underline underline-offset-4">
              Back to {child.displayName}&apos;s tutoring
            </Link>
          </p>
        ) : null}
      </div>
      <DirectoryView
        audience="member"
        tutorPath={(tutorId) => parentTutorHref(tutorId, childParam)}
        filters={filters}
        onFiltersChange={change}
        aside={
          <details className="max-w-prose">
            <summary className="cursor-pointer rounded-md py-1 text-body-sm text-ink-muted underline underline-offset-4">
              How tutors are ordered
            </summary>
            <p className="m-0 mt-2 text-body-sm text-ink-muted">{GRADE_RANKING_NOTE}</p>
          </details>
        }
      />
    </div>
  )
}

// ── A tutor's page ─────────────────────────────────────────────────────────

function Actions({ profile, childParam }: { profile: TutorProfile; childParam: string | null }) {
  const [open, setOpen] = useState(false)
  const report = useCreateTutoringReport()
  return (
    <>
      <Link
        to={parentBookHref(profile.tutorId, childParam)}
        className={cn(buttonVariants({ variant: "primary" }))}
      >
        Book a session
      </Link>
      <Button
        variant="ghost"
        onClick={() => {
          report.reset()
          setOpen(true)
        }}
      >
        Report
      </Button>
      <ReportSheet
        open={open}
        onClose={() => setOpen(false)}
        targetType="tutor_profile"
        targetLabel={profile.publicName}
        onSubmit={({ reason, details }) =>
          report.mutate({ targetType: "tutor_profile", targetId: profile.tutorId, reason, details })
        }
        pending={report.isPending}
        error={report.error}
        sent={report.isSuccess}
      />
    </>
  )
}

export function ParentTutorProfile() {
  const { tutorId = "" } = useParams()
  const [params] = useSearchParams()
  const childParam = params.get("child")
  const query = useTutorProfile(tutorId)
  const navigate = useNavigate()
  const directory = parentDirectoryHref(childParam)

  // A refusal the API made on purpose (a hidden tutor, an unconfirmed email) has its own
  // answer; every other failure is `QueryState`'s ordinary error or offline state.
  if (query.isError && bookingRefusalOf(query.error) !== null) {
    return (
      <>
        {/* `TutorFailure`'s heading is not an h1, and this is the whole page. */}
        <h1 className="sr-only">Tutor profile</h1>
        <TutorFailure error={query.error} onRetry={() => void query.refetch()} directoryPath={directory} />
      </>
    )
  }

  return (
    <QueryState
      query={query}
      skeleton={<TutorProfileSkeleton />}
      srHeading="Tutor profile"
      error={{
        heading: "We couldn't load this tutor",
        retryLabel: "Try again",
        secondaryAction: { label: "Find a tutor", onClick: () => navigate(directory) },
      }}
    >
      {(profile) => (
        <div className="flex flex-col gap-6 pt-2">
          <Link
            to={directory}
            className="inline-flex min-h-11 w-fit items-center gap-1.5 rounded-md text-body-sm text-ink-muted underline-offset-4 transition-colors hover:text-ink hover:underline active:text-ink"
          >
            <ArrowLeft size={16} aria-hidden />
            All tutors
          </Link>
          <TutorProfileView
            profile={profile}
            actions={<Actions profile={profile} childParam={childParam} />}
            results={<TutorOutcomes tutorId={profile.tutorId} />}
            reviews={<ReviewsSection tutorId={profile.tutorId} tutorName={profile.publicName} />}
          />
        </div>
      )}
    </QueryState>
  )
}

// ── The booking step ───────────────────────────────────────────────────────

function NoLinkedChild() {
  return (
    <EmptyState
      heading="Link a child to book"
      body="A tutor request is made for a child linked to your account. Your child adds you from their own Lemely account, under Parent access, so they stay in control of who sees their marks."
    >
      <Link to="/parent" className={buttonVariants({ variant: "accent", size: "sm" })}>
        Your children
      </Link>
    </EmptyState>
  )
}

function BookingFor({ tutor, linked }: { tutor: TutorProfile; linked: readonly ChildSummary[] }) {
  const [params] = useSearchParams()
  const [chosenId, setChosenId] = useState(() => preselectedChild(linked, params.get("child"))?.childId ?? "")
  // From the list, every time: an id that is not on it is no child.
  const chosen = resolveLinkedChild(linked, chosenId)

  return (
    <BookingForm
      audience="parent"
      tutor={tutor}
      student={chosen ? { id: chosen.childId, name: chosen.displayName } : undefined}
      childPicker={
        <Select
          label="Booking for"
          value={chosenId}
          onChange={(event) => setChosenId(event.target.value)}
        >
          {linked.length === 1 ? null : <option value="">Choose a child</option>}
          {linked.map((c) => (
            <option key={c.childId} value={c.childId}>
              {c.displayName}
            </option>
          ))}
        </Select>
      }
      sessionsPath={chosen ? parentChildTutoringHref(chosen.childId) : "/parent"}
      directoryPath={PARENT_TUTORS_PATH}
      bookedPath={(booking) => parentSessionHref(booking.student.studentId, booking.bookingId)}
      safetyNoticeOpen={false}
    />
  )
}

function Booking({ tutor }: { tutor: TutorProfile }) {
  const [params] = useSearchParams()
  const children = useChildren()
  return (
    <div className="flex w-full max-w-160 flex-col gap-6 pt-4">
      <div className="flex flex-col gap-2">
        <h1 className="m-0 text-display-md text-ink">Book a session with {tutor.publicName}</h1>
        <p className="m-0 text-body-md text-ink-muted">
          <Link to={parentTutorHref(tutor.tutorId, params.get("child"))} className="underline underline-offset-4">
            Back to their profile
          </Link>
        </p>
      </div>
      <QueryState
        query={children}
        skeleton={<ListSkeleton rows={3} />}
        error={{ heading: "We couldn't load your children", body: parentLoadFailureMessage }}
        isEmpty={(data) => data.children.length === 0}
        empty={<NoLinkedChild />}
      >
        {(data) => <BookingFor tutor={tutor} linked={data.children} />}
      </QueryState>
    </div>
  )
}

export function ParentBookSession() {
  const { tutorId = "" } = useParams()
  const profile = useTutorProfile(tutorId)
  const navigate = useNavigate()

  if (profile.isError && bookingRefusalOf(profile.error) !== null) {
    return (
      <>
        <h1 className="sr-only">Book a session</h1>
        <TutorFailure error={profile.error} onRetry={() => void profile.refetch()} directoryPath={PARENT_TUTORS_PATH} />
      </>
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
        secondaryAction: { label: "Find a tutor", onClick: () => navigate(PARENT_TUTORS_PATH) },
      }}
    >
      {(tutor) => <Booking tutor={tutor} />}
    </QueryState>
  )
}

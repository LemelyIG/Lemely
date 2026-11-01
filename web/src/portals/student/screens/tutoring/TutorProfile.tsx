/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — the page leads with the person and the one thing to do; sharing, reporting and blocking are present and plain, never decorated. */
import { useState } from "react"
import { ArrowLeft } from "@phosphor-icons/react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { Button, buttonVariants } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { QueryState } from "@/components/ui/query-state"
import { BlockSheet } from "@/components/tutoring/block-sheet"
import { ReportSheet } from "@/components/tutoring/report-sheet"
import { SHARE_ACCESS_PATH, ShareProgressSheet } from "@/components/tutoring/share-progress-sheet"
import {
  ReviewsSection,
  TutorFailure,
  TutorOutcomes,
  TutorProfileSkeleton,
  TutorProfileView,
} from "@/components/tutoring/tutor-profile-view"
import {
  useCreateTutorGrant,
  useCreateTutoringBlock,
  useCreateTutoringReport,
  useStudentTutorGrants,
  useTutorProfile,
} from "@/lib/hooks/useTutoringApi"
import { bookingRefusalOf } from "@/lib/tutoring/bookingErrors"
import { cn } from "@/lib/utils"
import type { TutorProfile as TutorProfileData } from "@/lib/tutoringTypes"

/*
 * S-34 · Tutor profile (`/student/tutors/:tutorId`, SPEC §d). The header, the
 * tutor's own words, weekly availability, the results section with its caption
 * and its hidden state, reviews, the fees line, and four actions: Book a
 * session, Share my progress, Report and Block.
 *
 * A tutor who is not listed, is paused, is suspended, is closed, is unknown or
 * has blocked the student is the same 404, and so the same answer here: "This
 * tutor isn't taking bookings right now." Nothing on this screen can say which
 * of those it was, or that a block was involved (SPEC §i.7).
 *
 * The sheets are the shared ones: sharing (S9) asks first and says what is
 * shared; Report (R1) is the one sheet used everywhere; Block (B2) lists what a
 * block does. A block takes the student back to the directory, because this
 * tutor's page is gone for them from then on. A live grant swaps "Share my
 * progress" for the fact that it is shared and the way to manage it.
 */

type Sheet = "share" | "report" | "block" | null

function Actions({ profile }: { profile: TutorProfileData }) {
  const navigate = useNavigate()
  const [sheet, setSheet] = useState<Sheet>(null)
  const grants = useStudentTutorGrants()
  const share = useCreateTutorGrant()
  const report = useCreateTutoringReport()
  const block = useCreateTutoringBlock()

  const sharing = (grants.data?.items ?? []).some(
    (grant) => grant.tutor.tutorId === profile.tutorId && grant.status === "active",
  )

  function open(next: Exclude<Sheet, null>) {
    // A sheet opened again starts from a clean attempt, not the last one's result.
    if (next === "share") share.reset()
    if (next === "report") report.reset()
    if (next === "block") block.reset()
    setSheet(next)
  }
  const close = () => setSheet(null)

  return (
    <>
      <Link to={`/student/tutors/${profile.tutorId}/book`} className={cn(buttonVariants({ variant: "primary" }))}>
        Book a session
      </Link>
      {sharing ? (
        <>
          <Chip tone="accent">Sharing your progress</Chip>
          <Link to={SHARE_ACCESS_PATH} className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}>
            Manage in Tutors &amp; your data
          </Link>
        </>
      ) : (
        <Button variant="secondary" onClick={() => open("share")}>
          Share my progress
        </Button>
      )}
      <Button variant="ghost" onClick={() => open("report")}>
        Report
      </Button>
      <Button variant="ghost" onClick={() => open("block")}>
        Block
      </Button>

      <ShareProgressSheet
        open={sheet === "share"}
        tutorName={profile.publicName}
        onCancel={close}
        onConfirm={() => share.mutate({ tutorId: profile.tutorId })}
        pending={share.isPending}
        error={share.error}
        shared={share.isSuccess}
      />
      <ReportSheet
        open={sheet === "report"}
        onClose={close}
        targetType="tutor_profile"
        targetLabel={profile.publicName}
        onSubmit={({ reason, details }) =>
          report.mutate({ targetType: "tutor_profile", targetId: profile.tutorId, reason, details })
        }
        pending={report.isPending}
        error={report.error}
        sent={report.isSuccess}
      />
      <BlockSheet
        open={sheet === "block"}
        viewer="student"
        counterpartName={profile.publicName}
        onCancel={close}
        onConfirm={() =>
          block.mutate({ tutorId: profile.tutorId }, { onSuccess: () => navigate("/student/tutors", { replace: true }) })
        }
        pending={block.isPending}
        error={block.error}
      />
    </>
  )
}

export function TutorProfile() {
  const { tutorId = "" } = useParams()
  const query = useTutorProfile(tutorId)
  const navigate = useNavigate()

  // A refusal the API made on purpose (a hidden tutor, an unconfirmed email) has its own
  // answer; every other failure is `QueryState`'s ordinary error or offline state.
  if (query.isError && bookingRefusalOf(query.error) !== null) {
    return (
      <TutorFailure error={query.error} onRetry={() => void query.refetch()} directoryPath="/student/tutors" />
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
        secondaryAction: { label: "Find a tutor", onClick: () => navigate("/student/tutors") },
      }}
    >
      {(profile) => (
        <div className="flex flex-col gap-6">
          <Link
            to="/student/tutors"
            className="inline-flex min-h-11 w-fit items-center gap-1.5 rounded-md text-body-sm text-ink-muted underline-offset-4 transition-colors hover:text-ink hover:underline active:text-ink"
          >
            <ArrowLeft size={16} aria-hidden />
            All tutors
          </Link>
          <TutorProfileView
            profile={profile}
            actions={<Actions profile={profile} />}
            results={<TutorOutcomes tutorId={profile.tutorId} />}
            reviews={<ReviewsSection tutorId={profile.tutorId} tutorName={profile.publicName} />}
          />
        </div>
      )}
    </QueryState>
  )
}

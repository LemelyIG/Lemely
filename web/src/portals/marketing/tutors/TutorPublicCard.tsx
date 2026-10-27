/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — the public card is deliberately small: a name, a headline, how they teach, and the one honest next step; the rest is behind sign-in. */
import { Link, Navigate, useLocation } from "react-router-dom"
import { MarketingFrame } from "@/portals/marketing"
import { NotFound } from "@/portals/misc/NotFound"
import { buttonVariants } from "@/components/ui/button"
import { TutorFailure, TutorProfileHeader, TutorProfileSkeleton } from "@/components/tutoring/tutor-profile-view"
import { usePublicTutor } from "@/lib/hooks/useTutoringApi"
import { NOINDEX_ROBOTS, classifyTutorPath, robotsForCard } from "@/lib/tutoring/robotsMeta"
import { cn } from "@/lib/utils"

/*
 * G-17 · Tutor public card (`/tutors/:tutorId`, public, SPEC §d): the public
 * fields only (P2), larger than in the directory, and "Sign in to book". An
 * unlisted, paused, suspended, closed or unknown tutor is one 404 and one
 * sentence: "This tutor isn't listed." with the way back to G-16.
 *
 * Search indexing (row 17, SPEC §b.5 "Client meta"): the tag is
 * `noindex, nofollow` unless P2 answered 200 with `indexable === true`, and
 * while P2 is loading or has failed. When the card is indexable there is no tag
 * at all, matching the worker's absent header. `robotsForCard` decides; this
 * screen renders what it says. The page also only answers to the canonical
 * address (`/tutors/{uuid}`); a variant is redirected or refused, never
 * rendered, because the worker serves variants with no robots header.
 *
 * The screen reads no field that is not on `PublicTutorCard`, so it cannot show
 * more than the open web may see (row 5b).
 */

const UNLISTED = "This tutor isn't listed."

function Card({ tutorId }: { tutorId: string }) {
  const query = usePublicTutor(tutorId)
  const robots = robotsForCard({ status: query.status, data: query.data })

  return (
    <MarketingFrame>
      {robots === null ? null : <meta name="robots" content={robots} />}
      <div className="mx-auto flex w-full max-w-marketing flex-col gap-8 px-page-mobile py-section md:px-page-tablet md:py-section-lg lg:px-page-desktop">
        {query.isPending ? (
          <>
            {/* The loaded card brings its own h1 (the tutor's name), and a failure brings TutorFailure's. */}
            <h1 className="sr-only">Tutor profile</h1>
            <TutorProfileSkeleton />
          </>
        ) : null}
        {query.isError ? (
          <TutorFailure
            error={query.error}
            onRetry={() => void query.refetch()}
            directoryPath="/tutors"
            unavailableHeading={UNLISTED}
          />
        ) : null}
        {query.isSuccess ? (
          <div className="flex max-w-3xl flex-col gap-6">
            <TutorProfileHeader tutor={query.data} />
            <div className="flex flex-wrap items-center gap-3">
              <Link
                to={`/login?next=${encodeURIComponent(`/student/tutors/${query.data.tutorId}`)}`}
                className={cn(buttonVariants({ variant: "primary" }))}
              >
                Sign in to book
              </Link>
              <Link to="/tutors" className={cn(buttonVariants({ variant: "ghost" }))}>
                All tutors
              </Link>
            </div>
            <p className="m-0 max-w-prose text-body-md text-ink-muted">
              Full profiles, availability, reviews and results are for people who sign in. Fees are agreed with the
              tutor, outside Lemely.
            </p>
          </div>
        ) : null}
      </div>
    </MarketingFrame>
  )
}

export function TutorPublicCard() {
  const { pathname, search } = useLocation()
  const page = classifyTutorPath(pathname)

  if (page.kind === "redirect") return <Navigate to={`${page.to}${search}`} replace />
  if (page.kind !== "card") {
    return (
      <>
        <meta name="robots" content={NOINDEX_ROBOTS} />
        <NotFound />
      </>
    )
  }
  return <Card tutorId={page.tutorId} />
}

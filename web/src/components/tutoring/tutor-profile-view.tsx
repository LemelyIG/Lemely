/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — the page is a document, not a dashboard: header, the person's own words, then the figures with their caveat in plain sight. */
import { useEffect, useRef, useState, type ReactNode } from "react"
import {
  DotsThreeCircle,
  FileText,
  MapPin,
  Star,
  Users,
  VideoCamera,
  type Icon,
} from "@phosphor-icons/react"
import { Link, useNavigate } from "react-router-dom"
import { Button, buttonVariants } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { GradeChangeSummary } from "@/components/ui/grade-change-summary"
import { OrdinalDistribution } from "@/components/ui/ordinal-distribution"
import { QueryState } from "@/components/ui/query-state"
import { RatingSummary } from "@/components/ui/rating-summary"
import { SkeletonBlock, SkeletonLine } from "@/components/ui/skeleton"
import { EmptyState, ErrorState, OfflineState, StateView } from "@/components/ui/state-views"
import { SubjectTag } from "@/components/ui/subject-tag"
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table"
import { useTutorOutcomes, useTutorReviews } from "@/lib/hooks/useTutoringApi"
import { isOfflineFailure } from "@/lib/offlineFailure"
import { describeQueryFailure } from "@/lib/queryFailure"
import { bookingRefusalOf, TUTOR_UNAVAILABLE_MESSAGE } from "@/lib/tutoring/bookingErrors"
import {
  DOCUMENTS_SEEN_DISCLOSURE,
  DOCUMENTS_SEEN_LABEL,
  FEES_LINE,
  NO_REVIEWS_LINE,
  availabilityRows,
  listedSinceLabel,
  resultsCaption,
} from "@/lib/tutoring/discovery"
import { distributionHidden, INSUFFICIENT_RESULTS_HEADING } from "@/lib/tutoring/ordinalLayout"
import { gradeChangeHidden } from "@/lib/tutoring/gradeChange"
import type {
  Outcomes,
  Review,
  ReviewsPage,
  TutorCard,
  TutorProfile,
  TutoringMode,
} from "@/lib/tutoringTypes"

/*
 * The tutor's page (SPEC §d, S-34; the same pieces serve G-17, P-07's profile
 * and T-21's preview). It is built from small parts a screen composes, because
 * each screen differs in what surrounds the facts: G-17 has only the public
 * card and a sign-in line, S-34 has the actions, T-21 passes the tutor's own
 * preview data in place of fetching.
 *
 *   - `TutorProfileHeader` takes a public card or a full profile and shows what
 *     it has: public name, headline, C-22, subjects, ways to meet and area, and
 *     for a full profile "Listed since" and "Documents seen by Lemely" with its
 *     disclosure. The documents badge is a fact about what an admin did, and the
 *     disclosure beside it says what it is not (a background check).
 *   - `AvailabilityTable` is a real table, seven rows, the zone label in its
 *     caption, a free day listed as "No times" and not left out.
 *   - `OutcomesPanel` / `TutorOutcomes` are the results section (ADR-T04): per
 *     subject, C-17 and C-18 side by side (stacked below 640px), each with its
 *     own `n` and table toggle, and one caption under the figures that says
 *     where the grades come from, that they are not examiner-accurate, and that
 *     they do not show what the tutor caused. A figure under the threshold is
 *     replaced by the hidden state; the caption is left out when every figure
 *     is hidden, because there is nothing for it to explain.
 *   - `ReviewsSection` pages reviews newest first, as a chain of pages like the
 *     directory. A review shows a star and number, "A student", the quarter, the
 *     approved text and the approved reply; never a name or a date.
 *   - `TutorFailure` is every way the page can fail: a hidden tutor is one
 *     "isn't taking bookings" answer that never implies a block, an unconfirmed
 *     email gets the way to confirm it, offline and other failures get a retry.
 *
 * Every string from the API is rendered as text and never parsed for links
 * (SC-7). Free-text blocks keep their line breaks and nothing else.
 */

const MODE: Record<TutoringMode, { label: string; icon: Icon }> = {
  virtual: { label: "Virtual", icon: VideoCamera },
  in_person: { label: "In person", icon: Users },
  other: { label: "Other", icon: DotsThreeCircle },
}

function isFullProfile(tutor: TutorCard | TutorProfile): tutor is TutorProfile {
  return "documentsSeen" in tutor
}

// ── Header ──────────────────────────────────────────────────────────────────

export interface TutorProfileHeaderProps {
  tutor: TutorCard | TutorProfile
  /** The page's own heading level: h1 on a page of its own. */
  headingAs?: "h1" | "h2"
  className?: string
}

export function TutorProfileHeader({ tutor, headingAs: Heading = "h1", className }: TutorProfileHeaderProps) {
  const full = isFullProfile(tutor) ? tutor : null
  const since = full ? listedSinceLabel(full.listedSince) : null
  return (
    <header className={className ?? "flex flex-col gap-3"}>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <Heading className="m-0 min-w-0 text-display-md text-ink">{tutor.publicName}</Heading>
        <RatingSummary rating={tutor.rating} />
      </div>
      <p className="m-0 text-body-lg text-ink-muted">{tutor.headline}</p>
      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Subjects">
        {tutor.subjects.map((subject) => (
          <li key={subject.code}>
            <SubjectTag subject={subject.name} />
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-body-md text-ink-muted">
        <ul className="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0" aria-label="Ways to meet">
          {tutor.modes.map((mode) => {
            const { label, icon: ModeIcon } = MODE[mode]
            return (
              <li key={mode} className="flex items-center gap-1">
                <ModeIcon size={16} aria-hidden />
                {label}
              </li>
            )
          })}
        </ul>
        <span className="flex items-center gap-1">
          <MapPin size={16} aria-hidden />
          <span className="sr-only">Area: </span>
          {tutor.area.name}
        </span>
        {since ? <span>Listed since {since}</span> : null}
      </div>
      {full?.documentsSeen ? (
        <details className="max-w-prose">
          <summary className="inline-flex cursor-pointer list-none items-center gap-2 rounded-md py-1 text-body-sm text-ink">
            <Chip tone="neutral" className="gap-1.5">
              <FileText size={14} aria-hidden />
              {DOCUMENTS_SEEN_LABEL}
            </Chip>
            <span className="text-ink-muted underline underline-offset-4">What this means</span>
          </summary>
          <p className="m-0 mt-2 text-body-sm text-ink-muted">{DOCUMENTS_SEEN_DISCLOSURE}</p>
        </details>
      ) : null}
    </header>
  )
}

// ── About ───────────────────────────────────────────────────────────────────

export function TutorAbout({ profile }: { profile: TutorProfile }) {
  return (
    <div className="flex flex-col gap-4">
      {profile.bio.trim() !== "" ? (
        <section aria-labelledby="tutor-about" className="flex flex-col gap-2">
          <h2 id="tutor-about" className="m-0 text-display-sm text-ink">
            About
          </h2>
          <p className="m-0 max-w-prose whitespace-pre-line text-body-md text-ink">{profile.bio}</p>
        </section>
      ) : null}
      {profile.qualificationNote ? (
        <p className="m-0 max-w-prose whitespace-pre-line text-body-md text-ink">
          <span className="text-label text-ink">Qualifications. </span>
          {profile.qualificationNote}
        </p>
      ) : null}
      {profile.modes.includes("other") && profile.otherModeNote ? (
        <p className="m-0 max-w-prose whitespace-pre-line text-body-md text-ink">
          <span className="text-label text-ink">Other way to meet. </span>
          {profile.otherModeNote}
        </p>
      ) : null}
      <p className="m-0 text-body-md text-ink-muted">{FEES_LINE}</p>
    </div>
  )
}

// ── Availability ────────────────────────────────────────────────────────────

export function AvailabilityTable({ profile }: { profile: Pick<TutorProfile, "availability" | "zoneLabel"> }) {
  const rows = availabilityRows(profile.availability)
  return (
    <section aria-labelledby="tutor-availability" className="flex flex-col gap-2">
      <h2 id="tutor-availability" className="m-0 text-display-sm text-ink">
        Weekly availability
      </h2>
      <Table density="operate">
        <caption className="px-4 py-2 text-start text-body-sm text-ink-muted">
          Usual times each week, in {profile.zoneLabel}. Open times for a date are shown when you book.
        </caption>
        <THead sticky={false}>
          <tr>
            <TH>Day</TH>
            <TH>Times</TH>
          </tr>
        </THead>
        <TBody>
          {rows.map((row) => (
            <TR key={row.isoWeekday}>
              <TH scope="row">{row.dayLabel}</TH>
              <TD>
                {row.ranges.length === 0 ? (
                  <span className="text-ink-muted">No times</span>
                ) : (
                  <span className="flex flex-col text-data-md">
                    {row.ranges.map((range) => (
                      <span key={range}>{range}</span>
                    ))}
                  </span>
                )}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </section>
  )
}

// ── Results ─────────────────────────────────────────────────────────────────

/** The results section for data already in hand (T-21's preview passes its own). */
export function OutcomesPanel({ outcomes }: { outcomes: Outcomes }) {
  const anyShown = outcomes.subjects.some(
    (s) => !distributionHidden(s.distribution) || !gradeChangeHidden(s.change),
  )
  return (
    <section aria-labelledby="tutor-results" className="flex flex-col gap-5">
      <h2 id="tutor-results" className="m-0 text-display-sm text-ink">
        Results with this tutor
      </h2>
      {outcomes.subjects.length === 0 ? (
        <StateView compact kind="empty" tone="neutral" heading={INSUFFICIENT_RESULTS_HEADING} />
      ) : (
        outcomes.subjects.map((entry) => (
          <div key={entry.subject.code} className="flex flex-col gap-3">
            <h3 className="m-0 text-body-lg font-medium text-ink">{entry.subject.name}</h3>
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <div className="flex min-w-0 flex-col gap-3">
                <h4 className="m-0 text-label text-ink">Grades during their time with this tutor</h4>
                <OrdinalDistribution
                  ladder={outcomes.ladder}
                  distribution={entry.distribution}
                  subjectName={entry.subject.name}
                />
              </div>
              <div className="min-w-0">
                <GradeChangeSummary change={entry.change} headingAs="h4" />
              </div>
            </div>
          </div>
        ))
      )}
      {anyShown ? (
        <p className="m-0 max-w-prose text-body-sm text-ink-muted">
          {resultsCaption(outcomes.duringWindowDays, outcomes.beforeLookbackDays)}
        </p>
      ) : null}
    </section>
  )
}

function OutcomesSkeleton() {
  return (
    <div className="flex flex-col gap-4" role="status" aria-label="Loading results">
      <SkeletonLine announce={false} className="h-6" width="40%" />
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <SkeletonBlock announce={false} className="h-24" />
        <SkeletonBlock announce={false} className="h-24" />
      </div>
    </div>
  )
}

/** SP4, fetched. A failure here is the section's own, not the page's. */
export function TutorOutcomes({ tutorId }: { tutorId: string }) {
  const query = useTutorOutcomes(tutorId)
  return (
    <QueryState
      query={query}
      skeleton={<OutcomesSkeleton />}
      error={{ heading: "We couldn't load the results", retryLabel: "Try again", compact: true }}
    >
      {(outcomes) => <OutcomesPanel outcomes={outcomes} />}
    </QueryState>
  )
}

// ── Reviews ─────────────────────────────────────────────────────────────────

function ReviewItem({
  review,
  tutorName,
  focusable,
}: {
  review: Review
  tutorName: string
  /** Takes focus when "Show more reviews" brings a new page in. */
  focusable: boolean
}) {
  return (
    <li
      tabIndex={focusable ? -1 : undefined}
      className="flex flex-col gap-2 border-t border-rule py-4 first:border-t-0 first:pt-0"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="inline-flex items-center gap-1.5 text-data-md text-ink">
          <Star size={16} weight="fill" className="text-pastel-amber-ink" aria-hidden />
          <span aria-hidden>{review.stars}</span>
          <span className="sr-only">{review.stars} out of 5</span>
        </span>
        <span className="text-body-sm text-ink-muted">A student</span>
        <span className="text-body-sm text-ink-faint">{review.period}</span>
      </div>
      {review.text ? <p className="m-0 max-w-prose whitespace-pre-line text-body-md text-ink">{review.text}</p> : null}
      {review.reply ? (
        <div className="ms-4 flex max-w-prose flex-col gap-1 border-s border-rule ps-4">
          <span className="text-label text-ink-muted">Reply from {tutorName}</span>
          <p className="m-0 whitespace-pre-line text-body-md text-ink">{review.reply.body}</p>
        </div>
      ) : null}
    </li>
  )
}

function ReviewsPageView({
  tutorId,
  tutorName,
  cursor,
  index,
  followed,
  onMore,
}: {
  tutorId: string
  tutorName: string
  cursor: string | null
  index: number
  followed: boolean
  onMore: (cursor: string) => void
}) {
  const query = useTutorReviews(tutorId, cursor ? { cursor } : {})
  return (
    <QueryState
      query={query}
      skeleton={
        <div className="flex flex-col gap-3" role="status" aria-label="Loading reviews">
          <SkeletonLine announce={false} width="30%" />
          <SkeletonLine announce={false} width="85%" />
        </div>
      }
      error={{ heading: "We couldn't load the reviews", retryLabel: "Try again", compact: true }}
      isEmpty={(page: ReviewsPage) => index === 0 && page.items.length === 0}
      empty={<p className="m-0 text-body-md text-ink-muted">{NO_REVIEWS_LINE}</p>}
    >
      {(page) => <ReviewList page={page} tutorName={tutorName} focusFirst={index > 0} canMore={!followed} onMore={onMore} />}
    </QueryState>
  )
}

function ReviewList({
  page,
  tutorName,
  focusFirst,
  canMore,
  onMore,
}: {
  page: ReviewsPage
  tutorName: string
  focusFirst: boolean
  canMore: boolean
  onMore: (cursor: string) => void
}) {
  const ref = useRef<HTMLUListElement>(null)
  useEffect(() => {
    if (focusFirst) ref.current?.querySelector<HTMLElement>("li")?.focus()
  }, [focusFirst])
  return (
    <>
      <ul ref={ref} className="m-0 flex list-none flex-col p-0">
        {page.items.map((review, i) => (
          <ReviewItem
            key={review.reviewId}
            review={review}
            tutorName={tutorName}
            focusable={i === 0 && focusFirst}
          />
        ))}
      </ul>
      {canMore && page.nextCursor ? (
        <div>
          <Button variant="secondary" size="sm" onClick={() => onMore(page.nextCursor as string)}>
            Show more reviews
          </Button>
        </div>
      ) : null}
    </>
  )
}

export function ReviewsSection({ tutorId, tutorName }: { tutorId: string; tutorName: string }) {
  const [cursors, setCursors] = useState<(string | null)[]>([null])
  return (
    <section aria-labelledby="tutor-reviews" className="flex flex-col gap-3">
      <h2 id="tutor-reviews" className="m-0 text-display-sm text-ink">
        Reviews
      </h2>
      {cursors.map((cursor, index) => (
        <ReviewsPageView
          key={cursor ?? "first"}
          tutorId={tutorId}
          tutorName={tutorName}
          cursor={cursor}
          index={index}
          followed={index < cursors.length - 1}
          onMore={(next) => setCursors((list) => (list.includes(next) ? list : [...list, next]))}
        />
      ))}
    </section>
  )
}

// ── Failure ─────────────────────────────────────────────────────────────────

export interface TutorFailureProps {
  error: unknown
  onRetry: () => void
  /** Where "Find a tutor" goes in this portal. */
  directoryPath: string
  /** Where a reader confirms their email. */
  verifyPath?: string
  /** Replaces S-34's wording where a screen has its own (G-17: "This tutor isn't listed."). */
  unavailableHeading?: string
}

/** Every way a tutor page can fail. A hidden tutor is one answer, never a hint of a block. */
export function TutorFailure({
  error,
  onRetry,
  directoryPath,
  verifyPath = "/verify-email",
  unavailableHeading = TUTOR_UNAVAILABLE_MESSAGE,
}: TutorFailureProps) {
  const navigate = useNavigate()
  const refusal = bookingRefusalOf(error)
  if (refusal?.action === "tutor_unavailable") {
    return (
      <EmptyState heading={unavailableHeading}>
        <Link to={directoryPath} className={buttonVariants({ variant: "accent", size: "sm" })}>
          Find a tutor
        </Link>
      </EmptyState>
    )
  }
  if (refusal?.action === "verify_email") {
    return (
      <EmptyState
        heading="Verify your email to see this profile."
        body="Full tutor profiles, reviews and results are for accounts with a confirmed email address."
        action={{ label: "Verify your email", onClick: () => navigate(verifyPath) }}
      />
    )
  }
  if (isOfflineFailure(error)) {
    return (
      <OfflineState
        heading="You're offline"
        body="This tutor's page needs a connection. Check yours and try again."
        action={{ label: "Try again", onClick: onRetry }}
      />
    )
  }
  return (
    <ErrorState
      heading="We couldn't load this tutor"
      body={describeQueryFailure(error)}
      action={{ label: "Try again", onClick: onRetry }}
      secondaryAction={{ label: "Find a tutor", onClick: () => navigate(directoryPath) }}
    />
  )
}

// ── Layout ──────────────────────────────────────────────────────────────────

export function TutorProfileSkeleton() {
  return (
    <div className="flex flex-col gap-6" role="status" aria-label="Loading tutor">
      <div className="flex flex-col gap-3">
        <SkeletonLine announce={false} className="h-8" width="min(22rem, 60%)" />
        <SkeletonLine announce={false} width="min(34rem, 85%)" />
        <SkeletonLine announce={false} className="h-6" width="40%" />
      </div>
      <SkeletonBlock announce={false} className="h-32" />
      <SkeletonBlock announce={false} className="h-48" />
    </div>
  )
}

export interface TutorProfileViewProps {
  profile: TutorProfile
  /** Buttons for this reader: Book, Share, Report, Block for a student. */
  actions?: ReactNode
  /** The results section: `<TutorOutcomes />`, or `<OutcomesPanel />` for a preview. */
  results?: ReactNode
  /** The reviews section: `<ReviewsSection />`. */
  reviews?: ReactNode
  className?: string
}

/** The S-34 page body, in the order a reader decides in: who, how to act, what they say, what the figures show. */
export function TutorProfileView({ profile, actions, results, reviews, className }: TutorProfileViewProps) {
  return (
    <div className={className ?? "flex flex-col gap-8"}>
      <TutorProfileHeader tutor={profile} />
      {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <div className="flex min-w-0 flex-col gap-8 lg:col-span-2">
          <TutorAbout profile={profile} />
          {results}
          {reviews}
        </div>
        <div className="min-w-0">
          <AvailabilityTable profile={profile} />
        </div>
      </div>
    </div>
  )
}

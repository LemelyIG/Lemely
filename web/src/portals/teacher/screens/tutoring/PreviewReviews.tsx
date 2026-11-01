/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — the profile as a student reads it, then the reviews with one quiet reply control each; moderation states are words, not colours; not yet seen in a browser. */
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { CheckCircle, HourglassMedium, PencilSimple, Star, WarningCircle } from "@phosphor-icons/react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { GradeChangeSummary } from "@/components/ui/grade-change-summary"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { OrdinalDistribution } from "@/components/ui/ordinal-distribution"
import { QueryState } from "@/components/ui/query-state"
import { RatingSummary } from "@/components/ui/rating-summary"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/state-views"
import { Table, TBody, TD, TH, TR } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { TutorCard } from "@/components/ui/tutor-card"
import {
  useOwnTutorProfile,
  useOwnTutorReviews,
  useReplyToReview,
  useTutorProfilePreview,
} from "@/lib/hooks/useTutoringApi"
import { useOnlineStatus } from "@/lib/online"
import { isTutoringError } from "@/lib/tutoring/apiErrors"
import { WEEKDAYS, formatMinute } from "@/lib/tutoring/availabilityEditor"
import {
  DOCUMENTS_SEEN_DISCLOSURE,
  DOCUMENTS_SEEN_LABEL,
  OUTCOMES_CAPTION,
  REPLY_CHECKED_LINE,
  REPLY_MAX,
  replyLength,
  formatListedSince,
  listingBanner,
  replyStateView,
  reviewTextNote,
  validateReply,
} from "@/lib/tutoring/profileSteps"
import { tutorActionFailureMessage, tutorLoadFailureMessage } from "@/lib/tutoring/tutorSessionActions"
import { cn } from "@/lib/utils"
import type { Outcomes, TutorOwnProfile, TutorPreview, TutorReviewItem } from "@/lib/tutoringTypes"

/*
 * T-21 · Profile preview and reviews (`/teacher/tutoring/preview`, SPEC §d).
 *
 * Two independent halves, each with its own loading, error and offline state so
 * one failing request never hides the other:
 *
 *   1. The profile exactly as a signed-in student reads it (T8): the public card
 *      (C-23), when the tutor was first listed, the "Documents seen" disclosure
 *      when it applies, the bio and notes, the weekly hours in the tutor's zone,
 *      and the results (C-17, C-18) for each subject. T8 returns no results for a
 *      profile that is not listed or under review, and the screen says so rather
 *      than drawing empty charts. The student's actions (book, share, report,
 *      block) are not drawn: this is a preview of the profile, not of the page's
 *      controls.
 *   2. The tutor's own reviews (T21): stars, the approved words (or a sentence
 *      about why they are not shown), the quarter, and the tutor's reply with
 *      its moderation state in words. A review with no reply has a Reply control;
 *      each review takes one reply, held for Lemely to check, and a refused
 *      contact detail uses the SPEC's sentence.
 *
 * Free text is plain text everywhere, never linked or parsed. Reviews load a
 * page at a time ("Show more reviews").
 *
 * Focus: sending a reply closes the composer and puts focus on the confirmation,
 * since the control that was in use is gone.
 */

const FIGURES = "grid grid-cols-1 gap-4 sm:grid-cols-2"

function Section({ id, title, children, action }: { id: string; title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={id} className="m-0 text-display-sm text-ink">
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  )
}

// ── The profile ─────────────────────────────────────────────────────────────

function WeeklyHours({ preview }: { preview: TutorPreview }) {
  const { availability, zoneLabel } = preview.profile
  const byDay = new Map<number, string[]>()
  for (const rule of availability) {
    const times = byDay.get(rule.isoWeekday) ?? []
    times.push(`${formatMinute(rule.startMinute)} to ${formatMinute(rule.endMinute)}`)
    byDay.set(rule.isoWeekday, times)
  }
  return (
    <div className="flex flex-col gap-2">
      <h3 className="m-0 text-label text-ink">Weekly hours, {zoneLabel}</h3>
      {availability.length === 0 ? (
        <p className="m-0 text-body-md text-ink-muted">No weekly hours are set, so students can't book you yet.</p>
      ) : (
        <Table density="operate" tabIndex={0} role="region" aria-label={`Weekly hours, ${zoneLabel}`}>
          <TBody>
            {WEEKDAYS.map((day) => {
              const times = byDay.get(day.iso)
              return (
                <TR key={day.iso}>
                  <TH scope="row" className="w-1/3 font-normal text-ink">
                    {day.label}
                  </TH>
                  <TD className={times ? "text-ink" : "text-ink-muted"}>{times ? times.join(", ") : "Not available"}</TD>
                </TR>
              )
            })}
          </TBody>
        </Table>
      )}
    </div>
  )
}

function ResultsBlock({ outcomes }: { outcomes: Outcomes | null }) {
  if (outcomes === null) {
    return (
      <p className="m-0 text-body-md text-ink-muted">
        Results appear here once your profile is listed or under review.
      </p>
    )
  }
  if (outcomes.subjects.length === 0) {
    return <p className="m-0 text-body-md text-ink-muted">There are no subjects to show results for yet.</p>
  }
  return (
    <div className="flex flex-col gap-6">
      {outcomes.subjects.map((subject) => (
        <div key={subject.subject.code} className="flex flex-col gap-3">
          <h4 className="m-0 text-label text-ink">{subject.subject.name}</h4>
          <div className={FIGURES}>
            <OrdinalDistribution
              ladder={outcomes.ladder}
              distribution={subject.distribution}
              subjectName={subject.subject.name}
            />
            <GradeChangeSummary change={subject.change} headingAs="h4" />
          </div>
        </div>
      ))}
      <p className="m-0 max-w-prose text-body-sm text-ink-muted">
        {OUTCOMES_CAPTION(outcomes.duringWindowDays, outcomes.beforeLookbackDays)}
      </p>
    </div>
  )
}

function ProfilePreview({ preview }: { preview: TutorPreview }) {
  const { profile } = preview
  const since = formatListedSince(profile.listedSince)
  return (
    <div className="flex flex-col gap-6">
      <TutorCard tutor={profile} headingAs="h3" />
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {since ? <span className="text-body-sm text-ink-muted">Listed since {since}</span> : null}
          {profile.documentsSeen ? (
            <Chip tone="info" className="gap-1.5">
              <CheckCircle size={14} weight="bold" aria-hidden />
              {DOCUMENTS_SEEN_LABEL}
            </Chip>
          ) : null}
        </div>
        {profile.documentsSeen ? (
          <p className="m-0 max-w-prose text-body-sm text-ink-muted">{DOCUMENTS_SEEN_DISCLOSURE}</p>
        ) : null}
      </div>

      {profile.bio ? (
        <div className="flex flex-col gap-1">
          <h3 className="m-0 text-label text-ink">About</h3>
          <p className="m-0 max-w-prose whitespace-pre-wrap break-words text-body-md text-ink">{profile.bio}</p>
        </div>
      ) : (
        <p className="m-0 text-body-md text-ink-muted">You haven't written an About text yet.</p>
      )}
      {profile.qualificationNote ? (
        <div className="flex flex-col gap-1">
          <h3 className="m-0 text-label text-ink">Qualifications</h3>
          <p className="m-0 max-w-prose whitespace-pre-wrap break-words text-body-md text-ink">
            {profile.qualificationNote}
          </p>
        </div>
      ) : null}
      {profile.otherModeNote ? (
        <div className="flex flex-col gap-1">
          <h3 className="m-0 text-label text-ink">Meeting another way</h3>
          <p className="m-0 max-w-prose whitespace-pre-wrap break-words text-body-md text-ink">
            {profile.otherModeNote}
          </p>
        </div>
      ) : null}

      <WeeklyHours preview={preview} />

      <div className="flex flex-col gap-3">
        <h3 className="m-0 text-label text-ink">Results with this tutor</h3>
        <ResultsBlock outcomes={preview.outcomes} />
      </div>

      <p className="m-0 text-body-sm text-ink-muted">Fees are agreed with the tutor, outside Lemely.</p>
    </div>
  )
}

function VisibilityNote({ own }: { own: TutorOwnProfile }) {
  if (own.listingState === "listed" && !own.paused) return null
  const banner = listingBanner(own.listingState, { paused: own.paused, reviewNote: own.reviewNote })
  return (
    <p className="m-0 flex items-start gap-2 rounded-md border border-rule bg-paper-sunk px-3 py-2.5 text-body-md text-ink">
      <WarningCircle size={18} className="mt-0.5 shrink-0 text-warn" aria-hidden />
      <span>
        <strong className="font-medium">Students can't see this yet.</strong> {banner.title}. {banner.body}
      </span>
    </p>
  )
}

// ── Reviews ─────────────────────────────────────────────────────────────────

function Stars({ stars }: { stars: number }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span role="img" aria-label={`${stars} out of 5 stars`} className="inline-flex">
        {Array.from({ length: 5 }, (_, index) => (
          <Star key={index} size={16} weight={index < stars ? "fill" : "regular"} className="text-ink" aria-hidden />
        ))}
      </span>
      <span className="text-body-sm text-ink-muted" aria-hidden>
        {stars} of 5
      </span>
    </span>
  )
}

const REPLY_ICON = { pending: HourglassMedium, approved: CheckCircle, rejected: WarningCircle } as const

function ReplyComposer({
  review,
  online,
  onSent,
}: {
  review: TutorReviewItem
  online: boolean
  onSent: () => void
}) {
  const reply = useReplyToReview()
  const [open, setOpen] = useState(false)
  const [body, setBody] = useState("")
  const [tried, setTried] = useState(false)
  const problem = validateReply(body)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    if (problem !== null) return
    try {
      await reply.mutateAsync({ reviewId: review.reviewId, body: { body: body.trim() } })
      setOpen(false)
      onSent()
    } catch {
      // Shown under the field.
    }
  }

  if (!open) {
    return (
      <div>
        <Button
          variant="secondary"
          size="sm"
          icon={<PencilSimple size={14} />}
          aria-label={`Reply to the ${review.stars}-star review from ${review.period}`}
          onClick={() => setOpen(true)}
        >
          Reply
        </Button>
      </div>
    )
  }

  const failure = reply.isError ? tutorActionFailureMessage(reply.error, "We couldn't send your reply. Try again.") : null
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-2">
      <Textarea
        label="Your reply"
        hint={`${REPLY_CHECKED_LINE} You can reply once, up to ${REPLY_MAX} characters.`}
        rows={3}
        value={body}
        autoFocus
        error={tried || replyLength(body) > REPLY_MAX ? (problem ?? undefined) : undefined}
        onChange={(event) => {
          setBody(event.target.value)
          if (reply.isError) reply.reset()
        }}
      />
      {failure ? (
        <p role="alert" className="m-0 text-body-sm text-err">
          {failure}
        </p>
      ) : null}
      {!online ? <p className="m-0 text-body-sm text-ink-muted">You're offline. Reconnect to send your reply.</p> : null}
      <div className="flex flex-wrap gap-3">
        <Button type="submit" variant="primary" size="sm" loading={reply.isPending} disabled={!online}>
          Send reply
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={reply.isPending}
          onClick={() => {
            setOpen(false)
            reply.reset()
          }}
        >
          Cancel
        </Button>
      </div>
    </form>
  )
}

function ReviewRow({ review, online }: { review: TutorReviewItem; online: boolean }) {
  const [justSent, setJustSent] = useState(false)
  const sentRef = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (justSent) sentRef.current?.focus()
  }, [justSent])
  const note = reviewTextNote(review.textState)
  const view = review.reply ? replyStateView(review.reply.textState) : null
  const ReplyGlyph = review.reply ? REPLY_ICON[review.reply.textState] : null
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <Stars stars={review.stars} />
        <span className="text-body-sm text-ink-muted">A student, {review.period}</span>
      </div>
      {review.text ? (
        <p className="m-0 max-w-prose whitespace-pre-wrap break-words text-body-md text-ink">{review.text}</p>
      ) : note ? (
        <p className="m-0 text-body-sm text-ink-muted">{note}</p>
      ) : (
        <p className="m-0 text-body-sm text-ink-muted">Stars only.</p>
      )}

      {review.reply && view && ReplyGlyph ? (
        <div className="flex flex-col gap-2 rounded-md bg-paper-sunk p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-label text-ink">Your reply</span>
            <Chip tone={view.tone} className="gap-1.5">
              <ReplyGlyph size={14} weight="bold" aria-hidden />
              {view.label}
            </Chip>
          </div>
          <p className="m-0 max-w-prose whitespace-pre-wrap break-words text-body-md text-ink">{review.reply.body}</p>
          <p className="m-0 text-body-sm text-ink-muted">{view.detail}</p>
        </div>
      ) : justSent ? null : (
        <ReplyComposer review={review} online={online} onSent={() => setJustSent(true)} />
      )}
      {justSent ? (
        <p ref={sentRef} tabIndex={-1} role="status" className="m-0 text-body-sm text-ok focus:outline-none">
          Your reply was sent. Lemely will check it before students see it.
        </p>
      ) : null}
    </li>
  )
}

function ReviewPages({ cursor, online }: { cursor?: string; online: boolean }) {
  const query = useOwnTutorReviews(cursor === undefined ? {} : { cursor })
  const [more, setMore] = useState(false)
  return (
    <QueryState
      query={query}
      skeleton={<ListSkeleton rows={2} />}
      error={{ heading: "Couldn't load your reviews", body: tutorLoadFailureMessage, compact: true }}
      isEmpty={(page) => cursor === undefined && page.items.length === 0}
      empty={<p className="m-0 text-body-md text-ink-muted">No reviews yet.</p>}
    >
      {(page) => (
        <>
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {page.items.map((review) => (
              <ReviewRow key={review.reviewId} review={review} online={online} />
            ))}
          </ul>
          {page.nextCursor ? (
            more ? (
              <ReviewPages cursor={page.nextCursor} online={online} />
            ) : (
              <div>
                <Button variant="secondary" size="sm" onClick={() => setMore(true)}>
                  Show more reviews
                </Button>
              </div>
            )
          ) : null}
        </>
      )}
    </QueryState>
  )
}

// ── The screen ──────────────────────────────────────────────────────────────

function PreviewSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <SkeletonBlock announce={false} className="h-32" />
      <SkeletonBlock announce={false} className="h-24" />
      <SkeletonBlock announce={false} className="h-40" />
    </div>
  )
}

export function PreviewReviews() {
  const previewQuery = useTutorProfilePreview()
  const ownQuery = useOwnTutorProfile()
  const online = useOnlineStatus()
  const navigate = useNavigate()

  if (isTutoringError(previewQuery.error, "no_tutor_profile")) {
    return (
      <div className="flex flex-col gap-5 min-w-0">
        <h1 className="sr-only">Profile preview and reviews</h1>
        <EmptyState
          heading="You don't have a tutor profile yet"
          body="Once you create one, you can see it here as students do, and read and reply to their reviews."
          action={{ label: "Set up your profile", onClick: () => void navigate("/teacher/tutoring/profile") }}
        />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-8 min-w-0">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-rule pb-5">
        <div className="flex flex-col gap-1">
          <h1 className="m-0 text-display-md text-ink">Profile preview and reviews</h1>
          <p className="m-0 text-body-md text-ink-muted">
            This is your profile as a signed-in student reads it, and what students have said about you.
          </p>
        </div>
        <Link to="/teacher/tutoring/profile" className={cn(buttonVariants({ variant: "secondary", size: "md" }))}>
          Edit your profile
        </Link>
      </div>

      {ownQuery.data ? <VisibilityNote own={ownQuery.data} /> : null}

      <Section id="preview-title" title="Your profile">
        <QueryState
          query={previewQuery}
          skeleton={<PreviewSkeleton />}
          error={{ heading: "Couldn't load your preview", body: tutorLoadFailureMessage }}
        >
          {(preview) => <ProfilePreview preview={preview} />}
        </QueryState>
      </Section>

      <Section
        id="reviews-title"
        title="Reviews"
        action={previewQuery.data ? <RatingSummary rating={previewQuery.data.profile.rating} /> : undefined}
      >
        <ReviewPages online={online} />
      </Section>
    </div>
  )
}

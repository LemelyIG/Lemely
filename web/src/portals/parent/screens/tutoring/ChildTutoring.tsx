/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — one column that answers "what is happening with tutors" for one child: two quiet links first, then who, then when; the same hairline list the student sees, in the parent's words. */
import type { ReactNode } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { BookingStatus } from "@/components/ui/booking-status"
import { Button } from "@/components/ui/button"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { Tabs, TabsList, TabsPanel } from "@/components/ui/tabs"
import { useChildren } from "@/lib/hooks/useParentApi"
import { useParentChildBookings } from "@/lib/hooks/useTutoringApi"
import { parentLoadFailureMessage } from "@/lib/parentOutcome"
import type { ChildSummary } from "@/lib/parentTypes"
import {
  findTutorLinkLabel,
  noSessionsLine,
  parentDirectoryHref,
  parentSessionHref,
  parentTutorAccessHref,
  resolveLinkedChild,
  tutorsFromBookings,
  whoSharesLinkLabel,
} from "@/lib/tutoring/parentTutoring"
import type { BookingWhen } from "@/lib/tutoring/queryKeys"
import { sessionRowView, usePagedItems, type SessionRowView } from "@/lib/tutoring/sessionView"
import type { Booking, BookingsPage } from "@/lib/tutoringTypes"

/*
 * P-05 · Child's tutoring (`/parent/children/:childId/tutoring`, SPEC §d). The
 * child's tutors (derived from their bookings) and their sessions with C-20,
 * and two ways on: "Who {child} shares progress with" (P-08) and "Find a tutor
 * for {child}" (P-07). A session opens P-06; a tutor opens the parent's page for
 * them.
 *
 * ── The child comes from the linked list ────────────────────────────────────
 * `ChildScope` resolves `:childId` against `GET /parent/children` before any
 * tutoring call is made. An id that is not on the list is one plain
 * "We couldn't find this child", whether it was mistyped, unlinked or someone
 * else's, so the screen is no oracle for who has children. The same wrapper
 * serves P-06 and P-08.
 *
 * States: skeleton while the child list or the sessions load; the C-11 error and
 * offline states with a retry (per tab, so one failing list does not blank the
 * page); "{Child} has no tutoring sessions." when both lists are empty; the
 * tabs' own empty lines when only one is.
 */

// ── The linked child ───────────────────────────────────────────────────────

function ChildNotFound({ srHeading }: { srHeading: string }) {
  return (
    <>
      {/* The state's own heading is not an h1, and this is the whole page. */}
      <h1 className="sr-only">{srHeading}</h1>
      <EmptyState
        heading="We couldn't find this child"
        body="Go back to your children to see who is linked to your account."
      >
        <Link
          to="/parent"
          className="inline-flex min-h-11 items-center rounded-md text-body-md text-accent-ink underline underline-offset-4"
        >
          Your children
        </Link>
      </EmptyState>
    </>
  )
}

/**
 * Renders `children` for the linked child `childId`, or the loading, error and
 * not-found states of the linked list. Shared by P-05, P-06 and P-08.
 */
export function ChildScope({
  childId,
  srHeading,
  children,
}: {
  childId: string
  srHeading: string
  children: (child: ChildSummary) => ReactNode
}) {
  const query = useChildren()
  return (
    <QueryState
      query={query}
      srHeading={srHeading}
      skeleton={
        <div className="flex flex-col gap-6">
          <PageHeaderSkeleton />
          <ListSkeleton rows={3} />
        </div>
      }
      error={{ heading: "We couldn't load your children", body: parentLoadFailureMessage }}
    >
      {(data) => {
        const child = resolveLinkedChild(data.children, childId)
        return child ? children(child) : <ChildNotFound srHeading={srHeading} />
      }}
    </QueryState>
  )
}

// ── Sessions ───────────────────────────────────────────────────────────────

interface BookingsScope {
  childId: string
  when: BookingWhen
}

const bookingKey = (booking: Booking) => booking.bookingId

function useParentBookingsPage(scope: BookingsScope, cursor: string | null) {
  return useParentChildBookings(scope.childId, { when: scope.when, cursor })
}

const ROW_CLASS =
  "relative flex flex-col gap-2 border-b border-rule px-4 py-4 transition-colors duration-[var(--dur-instant)] ease-out-soft last:border-b-0 hover:bg-paper-sunk focus-within:bg-paper-sunk active:bg-paper-sunk"

function SessionRow({ childId, row }: { childId: string; row: SessionRowView }) {
  return (
    <li className={ROW_CLASS}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <Link
          to={parentSessionHref(childId, row.bookingId)}
          aria-label={row.ariaLabel}
          className="min-w-0 break-words text-body-lg font-medium text-ink after:absolute after:inset-0"
        >
          {row.subjectName} with {row.tutorName}
        </Link>
        <BookingStatus state={row.state} />
      </div>
      <p className="m-0 text-body-md text-ink-muted">{row.timeLabel}</p>
      <p className="m-0 text-body-sm text-ink-muted">{row.modeLabel}</p>
    </li>
  )
}

function SessionList({
  childId,
  childName,
  when,
  paged,
}: {
  childId: string
  childName: string
  when: BookingWhen
  paged: ReturnType<typeof usePagedItems<BookingsScope, Booking, BookingsPage>>
}) {
  return (
    <QueryState
      query={paged.state}
      skeleton={<ListSkeleton rows={3} />}
      error={{ heading: `We couldn't load ${childName}'s sessions` }}
      isEmpty={(items) => items.length === 0}
      empty={
        <EmptyState
          compact
          heading={when === "upcoming" ? "No upcoming sessions." : "No past sessions yet."}
          body={
            when === "upcoming"
              ? `Requests and confirmed sessions for ${childName} appear here.`
              : "Sessions that have ended or were cancelled appear here."
          }
        />
      }
    >
      {(items) => (
        <div className="flex flex-col gap-4">
          <ul className="m-0 flex list-none flex-col overflow-hidden rounded-lg border border-rule bg-paper-raised p-0">
            {items.map((booking) => (
              <SessionRow key={booking.bookingId} childId={childId} row={sessionRowView(booking)} />
            ))}
          </ul>
          {paged.moreFailed ? (
            <p role="alert" className="m-0 text-body-sm text-err">
              We couldn't load more sessions. Press Show more sessions to try again.
            </p>
          ) : null}
          {paged.hasMore ? (
            <div>
              <Button
                variant="secondary"
                size="md"
                loading={paged.loadingMore}
                onClick={paged.moreFailed ? paged.retryMore : paged.loadMore}
              >
                Show more sessions
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </QueryState>
  )
}

// ── The screen ─────────────────────────────────────────────────────────────

const LINK_CLASS =
  "inline-flex min-h-11 items-center gap-1.5 rounded-md text-body-md text-accent-ink underline underline-offset-4 transition-colors hover:text-accent-hover active:text-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"

function ChildTutoringBody({ child }: { child: ChildSummary }) {
  const [params, setParams] = useSearchParams()
  const tab: BookingWhen = params.get("when") === "past" ? "past" : "upcoming"
  const upcoming = usePagedItems<BookingsScope, Booking, BookingsPage>(
    useParentBookingsPage,
    { childId: child.childId, when: "upcoming" },
    bookingKey,
  )
  const past = usePagedItems<BookingsScope, Booking, BookingsPage>(
    useParentBookingsPage,
    { childId: child.childId, when: "past" },
    bookingKey,
  )

  const loaded = upcoming.state.status === "success" && past.state.status === "success"
  const nothingAtAll = loaded && upcoming.items.length === 0 && past.items.length === 0
  const tutors = tutorsFromBookings([...upcoming.items, ...past.items], child.childId)

  return (
    <div className="flex w-full max-w-160 flex-col gap-8">
      <header className="flex flex-col gap-3">
        <h1 className="m-0 break-words text-display-md text-ink">{child.displayName}'s tutoring</h1>
        <nav aria-label={`Tutoring for ${child.displayName}`} className="flex flex-col items-start sm:flex-row sm:flex-wrap sm:gap-x-6">
          <Link to={parentTutorAccessHref(child.childId)} className={LINK_CLASS}>
            {whoSharesLinkLabel(child.displayName)}
            <CaretRight size={14} aria-hidden />
          </Link>
          <Link to={parentDirectoryHref(child.childId)} className={LINK_CLASS}>
            {findTutorLinkLabel(child.displayName)}
            <CaretRight size={14} aria-hidden />
          </Link>
        </nav>
      </header>

      {nothingAtAll ? (
        <EmptyState heading={noSessionsLine(child.displayName)} />
      ) : (
        <>
          {tutors.length > 0 ? (
            <section aria-labelledby="child-tutors" className="flex flex-col gap-3">
              <h2 id="child-tutors" className="m-0 text-display-sm text-ink">
                Tutors
              </h2>
              <ul className="m-0 flex list-none flex-col overflow-hidden rounded-lg border border-rule bg-paper-raised p-0">
                {tutors.map((tutor) => (
                  <li key={tutor.tutorId} className={ROW_CLASS}>
                    <Link
                      to={tutor.href}
                      className="min-w-0 break-words text-body-lg font-medium text-ink after:absolute after:inset-0"
                    >
                      {tutor.tutorName}
                    </Link>
                    <p className="m-0 text-body-sm text-ink-muted">{tutor.subjectLine}</p>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section aria-labelledby="child-sessions" className="flex flex-col gap-3">
            <h2 id="child-sessions" className="m-0 text-display-sm text-ink">
              Sessions
            </h2>
            <Tabs
              value={tab}
              onValueChange={(value) => setParams(value === "past" ? { when: "past" } : {}, { replace: true })}
            >
              <TabsList
                label="Sessions"
                tabs={[
                  { value: "upcoming", label: "Upcoming" },
                  { value: "past", label: "Past" },
                ]}
              />
              <TabsPanel value="upcoming" className="pt-4">
                <SessionList childId={child.childId} childName={child.displayName} when="upcoming" paged={upcoming} />
              </TabsPanel>
              <TabsPanel value="past" className="pt-4">
                <SessionList childId={child.childId} childName={child.displayName} when="past" paged={past} />
              </TabsPanel>
            </Tabs>
          </section>
        </>
      )}
    </div>
  )
}

export function ChildTutoring() {
  const { childId = "" } = useParams()
  return (
    <ChildScope key={childId} childId={childId} srHeading="Tutoring">
      {(child) => <ChildTutoringBody child={child} />}
    </ChildScope>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — rows are a hairline list with the whole row as one link and the state as icon plus word; two tabs and a paged list, so it stays quiet. Seen in a mock-API browser harness at 320 to 1440 px, light and dark, axe clean. */
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { BookingStatus } from "@/components/ui/booking-status"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { Tabs, TabsList, TabsPanel } from "@/components/ui/tabs"
import { useStudentBookings } from "@/lib/hooks/useTutoringApi"
import { sessionRowView, usePagedItems, type SessionRowView } from "@/lib/tutoring/sessionView"
import type { BookingWhen } from "@/lib/tutoring/queryKeys"
import type { Booking, BookingsPage } from "@/lib/tutoringTypes"

/*
 * S-36 · My sessions (`/student/sessions`, SPEC §d). Two tabs, Upcoming and
 * Past, each a list of the student's bookings: tutor, subject, time (the
 * tutor's zone, with its label), how they meet, and the C-20 state. A row opens
 * S-37.
 *
 * The tab is kept in the address (`?when=past`) so Back from a session lands on
 * the tab the student left. Each tab pages with "Show more sessions" (S1 is
 * keyset-paged; the split between upcoming and past is fixed in the cursor).
 *
 * States: skeleton rows while loading; the C-11 error and offline states from
 * `QueryState` with a retry; "No sessions booked." with a way to the directory
 * (S-33); "No past sessions yet.".
 *
 * One line under the tabs points at S-38 (Tutors & your data). The SPEC's exits
 * for S-36 are S-37 only, but S-38 has no navigation entry of its own and a
 * student who wants to stop sharing needs a way in that is not a tutor's page.
 */

const bookingKey = (booking: Booking) => booking.bookingId

function useBookingsPage(when: BookingWhen, cursor: string | null) {
  return useStudentBookings({ when, cursor })
}

function SessionRow({ row }: { row: SessionRowView }) {
  return (
    <li className="relative flex flex-col gap-2 border-b border-rule px-4 py-4 transition-colors duration-[var(--dur-instant)] ease-out-soft last:border-b-0 hover:bg-paper-sunk focus-within:bg-paper-sunk active:bg-paper-sunk">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <Link
          to={`/student/sessions/${encodeURIComponent(row.bookingId)}`}
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

function SessionList({ when }: { when: BookingWhen }) {
  const navigate = useNavigate()
  const paged = usePagedItems<BookingWhen, Booking, BookingsPage>(useBookingsPage, when, bookingKey)
  const upcoming = when === "upcoming"
  return (
    <QueryState
      query={paged.state}
      skeleton={<ListSkeleton rows={3} />}
      error={{ heading: "We couldn't load your sessions" }}
      isEmpty={(items) => items.length === 0}
      empty={
        upcoming ? (
          <EmptyState
            heading="No sessions booked."
            body="When you book a tutor, your sessions appear here."
            action={{ label: "Find a tutor", onClick: () => navigate("/student/tutors") }}
          />
        ) : (
          <EmptyState heading="No past sessions yet." body="Sessions that have ended or were cancelled appear here." />
        )
      }
    >
      {(items) => (
        <div className="flex flex-col gap-4">
          <ul className="m-0 flex list-none flex-col overflow-hidden rounded-lg border border-rule bg-paper-raised p-0">
            {items.map((booking) => (
              <SessionRow key={booking.bookingId} row={sessionRowView(booking)} />
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

export function Sessions() {
  const [params, setParams] = useSearchParams()
  const tab: BookingWhen = params.get("when") === "past" ? "past" : "upcoming"

  return (
    <div className="flex w-full max-w-160 flex-col gap-6">
      <h1 className="m-0 text-display-md text-ink">My sessions</h1>

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
          <SessionList when="upcoming" />
        </TabsPanel>
        <TabsPanel value="past" className="pt-4">
          <SessionList when="past" />
        </TabsPanel>
      </Tabs>

      <p className="m-0 max-w-prose text-body-sm text-ink-muted">
        You choose which tutors can see your progress. Manage that in{" "}
        <Link to="/student/tutor-access" className="text-accent-ink underline">
          Tutors &amp; your data
        </Link>
        .
      </p>
    </div>
  )
}

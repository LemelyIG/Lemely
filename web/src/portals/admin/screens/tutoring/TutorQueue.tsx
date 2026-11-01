/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 — a plain table, the name is the link, the one banner is the only thing that interrupts; not yet seen in a browser. */
import { useState, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Info } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Eyebrow } from "@/components/ui/primitives"
import { Select } from "@/components/ui/select"
import { EmptyState } from "@/components/ui/state-views"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { useAdminTutors } from "@/lib/hooks/useTutoringApi"
import {
  DEFAULT_QUEUE_STATE,
  QUEUE_STATES,
  adminFailureMessage,
  emailDeliveryNotice,
  formatAdminDay,
  queueEmpty,
} from "@/lib/tutoring/adminTutoring"
import type { AdminTutorState } from "@/lib/tutoring/queryKeys"
import type { AdminTutorItem } from "@/lib/tutoringTypes"

/*
 * X-04 · Tutor approval queue (`/platform/tutors`, SPEC §d, row A1).
 *
 * A table of tutors in one listing state, oldest first (the server's order),
 * waiting for review by default. The name opens X-05. The state filter lives in
 * the address (`?state=listed`) so Back from a tutor returns to the same list.
 *
 * "Email delivery: mock" is a banner above the table whenever A1 says mail is
 * not really being sent, because an approval then reaches the tutor in the app
 * only. It is read from the first page and shown in every state of the list.
 *
 * States: loading (a table-shaped skeleton), error and offline (through
 * `QueryState`, with retry), empty (per filter), more pages ("Load more", one
 * page at a time so the first rows never move).
 */

function parseState(raw: string | null): AdminTutorState {
  const match = QUEUE_STATES.find((state) => state.value === raw)
  return match ? match.value : DEFAULT_QUEUE_STATE
}

const COLUMNS = 2

function Rows({ items }: { items: readonly AdminTutorItem[] }) {
  return (
    <TBody>
      {items.map((tutor) => (
        <TR key={tutor.tutorId}>
          <TD>
            <div className="flex min-w-0 flex-col gap-1.5">
              <Link
                to={`/platform/tutors/${encodeURIComponent(tutor.tutorId)}`}
                className="inline-flex min-h-11 w-fit items-center rounded-sm text-body-md font-medium text-accent-ink underline underline-offset-2 transition-colors hover:text-accent-hover"
              >
                {tutor.publicName}
              </Link>
              <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Subjects">
                {tutor.subjects.map((subject) => (
                  <li key={subject.code}>
                    <Chip>{subject.name}</Chip>
                  </li>
                ))}
              </ul>
            </div>
          </TD>
          <TD className="whitespace-nowrap align-top text-body-sm text-ink-muted">
            {tutor.submittedAt ? (
              <time dateTime={tutor.submittedAt} className="tabular-nums">
                {formatAdminDay(tutor.submittedAt)}
              </time>
            ) : (
              "Not submitted"
            )}
          </TD>
        </TR>
      ))}
    </TBody>
  )
}

/** A line spanning the table: a note, or a control, in its own body. */
function SpanRow({ children }: { children: ReactNode }) {
  return (
    <TBody>
      <TR>
        <TD colSpan={COLUMNS}>{children}</TD>
      </TR>
    </TBody>
  )
}

/** The next page, fetched only once asked for, then its own "Load more" if there is another. */
function MoreRows({ state, cursor }: { state: AdminTutorState; cursor: string }) {
  const [asked, setAsked] = useState(false)
  if (!asked) {
    return (
      <SpanRow>
        <Button className="min-h-11" size="sm" onClick={() => setAsked(true)}>
          Load more
        </Button>
      </SpanRow>
    )
  }
  return <NextRows state={state} cursor={cursor} />
}

function NextRows({ state, cursor }: { state: AdminTutorState; cursor: string }) {
  const query = useAdminTutors({ state, cursor })
  if (query.isPending) {
    return (
      <SpanRow>
        <p role="status" className="m-0 text-body-sm text-ink-muted">
          Loading more tutors
        </p>
      </SpanRow>
    )
  }
  if (query.isError) {
    return (
      <SpanRow>
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="m-0 text-body-sm text-ink">
            {adminFailureMessage(query.error, "We couldn't load more tutors.")}
          </p>
          <Button className="min-h-11" size="sm" onClick={() => void query.refetch()}>
            Try again
          </Button>
        </div>
      </SpanRow>
    )
  }
  return (
    <>
      <Rows items={query.data.items} />
      {query.data.nextCursor ? <MoreRows state={state} cursor={query.data.nextCursor} /> : null}
    </>
  )
}

export function TutorQueue() {
  const [params, setParams] = useSearchParams()
  const state = parseState(params.get("state"))
  const query = useAdminTutors({ state })
  const notice = emailDeliveryNotice(query.data?.emailDelivery)

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>Platform admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Tutors</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          Profiles tutors have submitted, oldest first. Open one to read it and decide.
        </p>
      </header>

      {notice ? (
        <div
          role="status"
          className="flex items-start gap-3 rounded-lg border border-rule bg-warn-wash px-4 py-3"
        >
          <Info size={20} className="mt-0.5 flex-none text-warn" aria-hidden="true" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <p className="m-0 text-body-md font-medium text-ink">{notice.title}</p>
            <p className="m-0 max-w-prose text-body-sm text-ink-muted">{notice.body}</p>
          </div>
        </div>
      ) : null}

      <Select
        label="Show"
        className="min-h-11"
        value={state}
        wrapperClassName="w-full sm:w-64"
        onChange={(event) => {
          const next = new URLSearchParams(params)
          if (event.target.value === DEFAULT_QUEUE_STATE) next.delete("state")
          else next.set("state", event.target.value)
          setParams(next, { replace: true })
        }}
      >
        {QUEUE_STATES.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>

      <QueryState
        query={query}
        skeleton={<ListSkeleton rows={4} />}
        error={{
          heading: "We couldn't load the tutors",
          body: (error) => adminFailureMessage(error, "Something went wrong loading this list. Try again."),
        }}
        isEmpty={(page) => page.items.length === 0}
        empty={
          <EmptyState
            heading={queueEmpty(state).heading}
            body={queueEmpty(state).body}
            marginalia="all clear"
          />
        }
      >
        {(page) => (
          <Table density="operate">
            <THead>
              <TR>
                <TH>Tutor</TH>
                <TH>Submitted</TH>
              </TR>
            </THead>
            <Rows items={page.items} />
            {page.nextCursor ? <MoreRows state={state} cursor={page.nextCursor} /> : null}
          </Table>
        )}
      </QueryState>
    </div>
  )
}

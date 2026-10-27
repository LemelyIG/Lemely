/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 — a plain table, safety concerns marked by icon and word; not yet seen in a browser. */
import { useState, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Warning } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { Eyebrow } from "@/components/ui/primitives"
import { QueryState } from "@/components/ui/query-state"
import { Select } from "@/components/ui/select"
import { EmptyState } from "@/components/ui/state-views"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { useAdminTutoringReports } from "@/lib/hooks/useTutoringApi"
import {
  REPORT_STATES,
  adminFailureMessage,
  formatAdminDay,
  isSafetyConcern,
  reportReasonLabel,
  reportTargetLabel,
} from "@/lib/tutoring/adminTutoring"
import type { ReportItem } from "@/lib/tutoringTypes"

/*
 * X-07 · Reports queue (`/platform/reports`, SPEC §d, row A9).
 *
 * Reports in one state, open by default, safety concerns first (the server's
 * order; the list never re-sorts). A safety concern carries a warning icon and
 * the words, never colour alone. The reason is the link to the report; the line under
 * it says what was reported. The state filter lives in the address.
 *
 * States: loading, error and offline (through `QueryState`, with retry), empty
 * (per filter), more pages ("Load more").
 */

type State = ReportItem["state"]

function parseState(raw: string | null): State {
  const match = REPORT_STATES.find((state) => state.value === raw)
  return match ? match.value : "open"
}

const COLUMNS = 2

const EMPTY: Record<State, { heading: string; body: string }> = {
  open: {
    heading: "No open reports",
    body: "Reports appear here when someone files one. Safety concerns come first.",
  },
  dismissed: { heading: "No dismissed reports", body: "Reports you dismiss are listed here." },
  actioned: { heading: "No actioned reports", body: "Reports that ended in an action are listed here." },
}

function Rows({ items }: { items: readonly ReportItem[] }) {
  return (
    <TBody>
      {items.map((item) => (
        <TR key={item.reportId}>
          <TD>
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="flex items-center gap-2">
                {isSafetyConcern(item) ? (
                  <Warning size={18} weight="fill" className="flex-none text-err" aria-hidden="true" />
                ) : null}
                <Link
                  to={`/platform/reports/${encodeURIComponent(item.reportId)}`}
                  className="inline-flex min-h-11 items-center rounded-sm text-body-md font-medium text-accent-ink underline underline-offset-2 transition-colors hover:text-accent-hover"
                >
                  {reportReasonLabel(item.reason)}
                </Link>
              </span>
              <span className="text-body-sm text-ink-muted">{reportTargetLabel(item.targetType)}</span>
            </div>
          </TD>
          <TD className="whitespace-nowrap align-top text-body-sm text-ink-muted">
            <time dateTime={item.createdAt} className="tabular-nums">
              {formatAdminDay(item.createdAt)}
            </time>
          </TD>
        </TR>
      ))}
    </TBody>
  )
}

function SpanRow({ children }: { children: ReactNode }) {
  return (
    <TBody>
      <TR>
        <TD colSpan={COLUMNS}>{children}</TD>
      </TR>
    </TBody>
  )
}

function MoreRows({ state, cursor }: { state: State; cursor: string }) {
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

function NextRows({ state, cursor }: { state: State; cursor: string }) {
  const query = useAdminTutoringReports({ state, cursor })
  if (query.isPending) {
    return (
      <SpanRow>
        <p role="status" className="m-0 text-body-sm text-ink-muted">
          Loading more reports
        </p>
      </SpanRow>
    )
  }
  if (query.isError) {
    return (
      <SpanRow>
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="m-0 text-body-sm text-ink">
            {adminFailureMessage(query.error, "We couldn't load more reports.")}
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

export function Reports() {
  const [params, setParams] = useSearchParams()
  const state = parseState(params.get("state"))
  const query = useAdminTutoringReports({ state })

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>Platform admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Reports</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          Things students, parents and tutors have reported. Safety concerns come first.
        </p>
      </header>

      <Select
        label="Show"
        className="min-h-11"
        value={state}
        wrapperClassName="w-full sm:w-64"
        onChange={(event) => {
          const next = new URLSearchParams(params)
          if (event.target.value === "open") next.delete("state")
          else next.set("state", event.target.value)
          setParams(next, { replace: true })
        }}
      >
        {REPORT_STATES.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>

      <QueryState
        query={query}
        skeleton={<ListSkeleton rows={4} />}
        error={{
          heading: "We couldn't load the reports",
          body: (error) => adminFailureMessage(error, "Something went wrong loading this list. Try again."),
        }}
        isEmpty={(page) => page.items.length === 0}
        empty={<EmptyState heading={EMPTY[state].heading} body={EMPTY[state].body} marginalia="all clear" />}
      >
        {(page) => (
          <Table density="operate">
            <THead>
              <TR>
                <TH>Report</TH>
                <TH>Reported</TH>
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

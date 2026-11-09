/* Hallmark · pre-emit critique: P4 H4 E5 S4 R4 V4 */
/* E5: a phone gets stacked cards and larger screens a table (one hidden at any width), a failed next page keeps the rows, focus returns to a real control after each load, and the live region says how many rows arrived. */
import type { InfiniteData, UseInfiniteQueryResult } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { OwnAccountNote } from "@/components/acting/own-account-note"
import { Button, buttonVariants } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { formatBillingDate } from "@/lib/billingFormat"
import type { UsageHistoryPage, UsageJobRow } from "@/lib/billingTypes"
import { billingPaths } from "@/lib/billingPaths"
import { useUsageHistory } from "@/lib/hooks/useUsageApi"
import {
  actionLabel,
  historyPhase,
  jobChargeText,
  jobEstimateText,
  jobStatusText,
  moreLoadedText,
} from "@/lib/usageHistoryModel"

/*
 * Usage history (spec §2.4): one row per metered job, estimate against actual. This is the
 * whole record of usage; there are no usage receipts. It serves the signed-in caller only
 * (M6), so a parent has no view of a child's history. Allowance rows carry display values
 * (a share of the plan), never raw units, so allowance sizes stay hidden (spec §2.1).
 *
 * A phone gets a stacked card per job instead of the table: five columns would scroll sideways
 * and hide the one column that matters ("Charged"). One of the two is `display: none` at any
 * width, so assistive tech reads the history once.
 *
 * The status sits under the action rather than in a column of its own: most rows are simply
 * done, so a "Done" column would repeat itself down the page and push the two money columns
 * off a phone. Only a job that is not done says anything extra.
 */

function JobCard({ row }: { row: UsageJobRow }) {
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-outline-variant bg-surface-container-lowest p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="text-body-md font-semibold text-on-surface">{actionLabel(row.action)}</span>
        <span className="text-body-sm text-on-surface-variant">{formatBillingDate(row.createdAt)}</span>
      </div>
      {row.status !== "settled" ? <p className="m-0 text-body-sm text-on-surface-variant">{jobStatusText(row)}</p> : null}
      <dl className="m-0 grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-1">
        <dt className="text-body-sm text-on-surface-variant">Estimate</dt>
        <dd className="m-0 text-end text-data-sm text-on-surface-variant">{jobEstimateText(row)}</dd>
        <dt className="text-body-sm text-on-surface-variant">Charged</dt>
        <dd className="m-0 text-end text-data-sm text-on-surface">{jobChargeText(row)}</dd>
      </dl>
    </li>
  )
}

/* One list of jobs, drawn twice: a stacked card per job on a phone, the table from `sm` up. */
function HistoryRows({ jobs }: { jobs: UsageJobRow[] }) {
  return (
    <>
      <ul aria-label="Usage history" className="m-0 flex list-none flex-col gap-3 p-0 sm:hidden">
        {jobs.map((row) => (
          <JobCard key={row.jobId} row={row} />
        ))}
      </ul>
      <Table className="max-sm:hidden">
        <caption className="sr-only">Usage history</caption>
        <THead>
          <TR>
            <TH>Date</TH>
            <TH>Action</TH>
            <TH numeric>Estimate</TH>
            <TH numeric>Charged</TH>
          </TR>
        </THead>
        <TBody>
          {jobs.map((row) => (
            <TR key={row.jobId}>
              <TD className="whitespace-nowrap text-on-surface-variant">{formatBillingDate(row.createdAt)}</TD>
              <TD>
                <span className="block">{actionLabel(row.action)}</span>
                {row.status !== "settled" ? (
                  <span className="block text-body-sm text-on-surface-variant">{jobStatusText(row)}</span>
                ) : null}
              </TD>
              <TD numeric className="text-on-surface-variant">
                {jobEstimateText(row)}
              </TD>
              <TD numeric>{jobChargeText(row)}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </>
  )
}

type History = UseInfiniteQueryResult<InfiniteData<UsageHistoryPage, string | null>, Error>

/*
 * The loaded rows plus the "Load more" control. A failed page keeps the rows on screen and says
 * so beside the button. After a page loads, keyboard focus has to land somewhere real: the button
 * is disabled while it fetches (which drops focus) and disappears on the last page, so focus
 * returns to the button, or to the closing note when there is nothing more to load. The polite
 * live region says how many rows arrived.
 */
function HistoryList({ history }: { history: History }) {
  const jobs = history.data?.pages.flatMap((p) => p.jobs) ?? []
  const [announce, setAnnounce] = useState("")
  const [refocus, setRefocus] = useState(false)
  const moreRef = useRef<HTMLButtonElement>(null)
  const endRef = useRef<HTMLParagraphElement>(null)
  const { hasNextPage, isFetchingNextPage } = history

  useEffect(() => {
    if (!refocus || isFetchingNextPage) return
    ;(hasNextPage ? moreRef.current : endRef.current)?.focus()
    setRefocus(false)
  }, [refocus, isFetchingNextPage, hasNextPage])

  const loadMore = async () => {
    const before = jobs.length
    const result = await history.fetchNextPage()
    if (!result.isFetchNextPageError && result.data) {
      setAnnounce(moreLoadedText(result.data.pages.flatMap((p) => p.jobs).length - before))
    }
    setRefocus(true)
  }

  return (
    <>
      <HistoryRows jobs={jobs} />
      <p role="status" className="sr-only">
        {announce}
      </p>
      {history.isFetchNextPageError ? (
        <p role="alert" className="m-0 text-body-sm text-on-surface">
          Couldn't load more of your usage.
        </p>
      ) : null}
      {hasNextPage ? (
        <div>
          <Button ref={moreRef} variant="secondary" loading={isFetchingNextPage} onClick={() => void loadMore()}>
            {history.isFetchNextPageError ? "Try again" : "Load more"}
          </Button>
        </div>
      ) : (history.data?.pages.length ?? 0) > 1 ? (
        <p ref={endRef} tabIndex={-1} className="m-0 text-body-sm text-on-surface-variant focus:outline-none">
          That's all of your usage.
        </p>
      ) : null}
    </>
  )
}

export function UsageHistoryView({ backHref }: { backHref: string }) {
  const history = useUsageHistory()
  const phase = historyPhase(history)
  return (
    <div className="flex flex-col gap-6">
      <h1 className="m-0 text-display-md text-on-surface">Usage history</h1>
      {phase === "first-load" ? (
        // Only the first page's failure is a full-page error; `historyPhase` is "list" once any page loaded.
        <QueryState query={history} skeleton={<ListSkeleton />} error={{ heading: "Couldn't load your usage history" }}>
          {() => null}
        </QueryState>
      ) : phase === "empty" ? (
        <EmptyState
          kicker={null}
          heading="No usage yet."
          body="Jobs you run appear here with their estimate and what they actually cost."
        >
          <Link to={backHref} className={buttonVariants({ variant: "secondary" })}>
            Back to plan and billing
          </Link>
        </EmptyState>
      ) : (
        <HistoryList history={history} />
      )}
    </div>
  )
}

export function StudentUsageHistory() {
  return <UsageHistoryView backHref={billingPaths({ role: "student" }).overview} />
}

export function TeacherUsageHistory() {
  return (
    <>
      <OwnAccountNote />
      <UsageHistoryView backHref={billingPaths({ role: "teacher" }).overview} />
    </>
  )
}

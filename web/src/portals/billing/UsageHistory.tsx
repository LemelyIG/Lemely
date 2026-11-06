import { Link } from "react-router-dom"
import { Button, buttonVariants } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { formatBillingDate } from "@/lib/billingFormat"
import type { UsageJobRow } from "@/lib/billingTypes"
import { billingPaths } from "@/lib/billingPaths"
import { useUsageHistory } from "@/lib/hooks/useUsageApi"
import { actionLabel, jobChargeText, jobEstimateText, jobStatusText } from "@/lib/usageHistoryModel"

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

export function UsageHistoryView({ backHref }: { backHref: string }) {
  const history = useUsageHistory()
  return (
    <div className="flex flex-col gap-6">
      <h1 className="m-0 text-display-md text-on-surface">Usage history</h1>
      <QueryState
        query={history}
        skeleton={<ListSkeleton />}
        error={{ heading: "Couldn't load your usage history" }}
        isEmpty={(d) => d.pages.every((p) => p.jobs.length === 0)}
        empty={
          <EmptyState
            kicker={null}
            heading="No usage yet."
            body="Jobs you run appear here with their estimate and what they actually cost."
          >
            <Link to={backHref} className={buttonVariants({ variant: "secondary" })}>
              Back to plan and billing
            </Link>
          </EmptyState>
        }
      >
        {(d) => (
          <>
            <HistoryRows jobs={d.pages.flatMap((p) => p.jobs)} />
            {history.hasNextPage ? (
              <div>
                <Button
                  variant="secondary"
                  loading={history.isFetchingNextPage}
                  onClick={() => void history.fetchNextPage()}
                >
                  Load more
                </Button>
              </div>
            ) : null}
          </>
        )}
      </QueryState>
    </div>
  )
}

export function StudentUsageHistory() {
  return <UsageHistoryView backHref={billingPaths({ role: "student" }).overview} />
}

export function TeacherUsageHistory() {
  return <UsageHistoryView backHref={billingPaths({ role: "teacher" }).overview} />
}

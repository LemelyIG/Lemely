/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import type { ReactNode } from "react"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { ErrorState } from "@/components/ui/state-views"
import { formatUtc, isForbidden } from "@/lib/adminBillingModel"
import { jobOutcomeText, jobRunsText, webhookErrorText } from "@/lib/adminOpsModel"
import type { BillingHealth, SweeperJobHealth } from "@/lib/billingTypes"
import { useBillingHealth } from "@/lib/hooks/useAdminBillingApi"
import { cn } from "@/lib/utils"
import { RefreshNote } from "./RefreshNote"

/*
 * Billing health (spec §8.5): only what the server recorded. A job that never ran says so, a
 * job whose last run failed says what it said and how many runs in a row, and a webhook window
 * with no events says "No webhooks" rather than 0% failed. Nothing here is guessed or smoothed.
 * Refreshes every minute through the hook.
 */

const n = (v: number) => new Intl.NumberFormat("en-US").format(v)
const LIST = "m-0 flex list-none flex-col divide-y divide-outline-variant overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest p-0"

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="m-0 text-display-sm text-on-surface">{title}</h2>
      {children}
    </section>
  )
}

/** Weight, not colour, separates a count that needs a look from a zero. */
function CountRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-baseline justify-between gap-4 px-4 py-2.5">
      <dt className="text-body-md text-on-surface">{label}</dt>
      <dd className={cn("m-0 text-data-md", value > 0 ? "font-semibold text-on-surface" : "text-on-surface-variant")}>{n(value)}</dd>
    </div>
  )
}

function JobRow({ job }: { job: SweeperJobHealth }) {
  const failed = !job.neverRun && job.lastOutcome === "failed"
  return (
    <li className="flex flex-col gap-1 px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="min-w-0 break-all text-data-sm text-on-surface">{job.name}</span>
        <span className="text-body-sm text-on-surface-variant">{job.lastFinishedAt ? `Finished ${formatUtc(job.lastFinishedAt)}` : "Not finished yet"}</span>
      </div>
      <p className={cn("m-0 text-body-md", failed ? "font-medium text-error" : "text-on-surface")}>{jobOutcomeText(job)}</p>
      <p className="m-0 text-body-sm text-on-surface-variant">
        {jobRunsText(job)}
        {failed ? (job.lastSuccessAt ? ` · last success ${formatUtc(job.lastSuccessAt)}` : " · no success recorded") : ""}
      </p>
    </li>
  )
}

function Loaded({ h }: { h: BillingHealth }) {
  return (
    <div className="flex flex-col gap-10">
      <Section title="Webhooks">
        <p className="m-0 text-data-md text-on-surface">{webhookErrorText(h)}</p>
      </Section>
      <Section title="Recorded problems">
        <dl className="m-0 divide-y divide-outline-variant overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest">
          <CountRow label="Amount mismatches" value={h.mismatches} />
          <CountRow label="Renewal failures" value={h.renewalFailureEvents} />
          <CountRow label="Past due now" value={h.pastDueNow} />
          <CountRow label="Failed auto top-ups" value={h.failedAutoTopups} />
          <CountRow label="Failed extra-seat charges" value={h.failedExtraSeatCharges} />
        </dl>
      </Section>
      <Section title="Sweeper jobs">
        {h.jobs.length === 0 ? (
          <p className="m-0 text-body-md text-on-surface-variant">The server lists no sweeper jobs.</p>
        ) : (
          <ul className={LIST}>
            {h.jobs.map((j) => (
              <JobRow key={j.name} job={j} />
            ))}
          </ul>
        )}
      </Section>
      <p className="m-0 text-body-sm text-on-surface-variant">Counts cover the last {h.windowHours} hours. Refreshes every minute.</p>
    </div>
  )
}

export function Health() {
  const health = useBillingHealth()
  if (health.status === "error" && isForbidden(health.error)) {
    return <ErrorState kicker={null} heading="You can't open billing health" body="Billing is for platform admins. Ask one to look at this." />
  }
  return (
    <div className="flex flex-col gap-6">
      {health.data === undefined ? (
        <QueryState
          query={health}
          skeleton={
            <div className="flex flex-col gap-6">
              <PageHeaderSkeleton />
              <ListSkeleton rows={4} />
            </div>
          }
          error={{ heading: "Couldn't load billing health" }}
        >
          {() => null}
        </QueryState>
      ) : (
        <>
          <RefreshNote query={health} />
          <Loaded h={health.data} />
        </>
      )}
    </div>
  )
}

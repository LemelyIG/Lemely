import type { ReactNode } from "react"
import type { Audience } from "@/lib/billingTypes"
import { estimateSentence } from "@/lib/billingFormat"
import type { BillingPaths } from "@/lib/billingPaths"
import { isRecheckingBlock, type MeteredGate } from "@/lib/meteredGate"
import { UsageBlockedNotice } from "./usage-blocked-notice"

/*
 * The estimate shown before every metered action (spec §2.4, §5.7 step 1). The range is a
 * promise about the top only: the job starts if the balance covers the top, and charges the
 * actual cost when it ends. `subjectUnknown` is for upload screens, where the server cannot
 * yet route the job to a teacher's seat because the paper's subject is detected later.
 */

export function EstimateRange({
  gate,
  audience,
  paths,
  managedByName,
  subjectUnknown = false,
  headingLevel,
}: {
  gate: MeteredGate
  audience: Audience
  paths: BillingPaths | null
  managedByName: string | null
  subjectUnknown?: boolean
  headingLevel?: 2 | 3 | 4
}) {
  // The polite region stays mounted with no request so the first estimate that lands is announced
  // (a region inserted together with its content is often missed). `empty:sr-only` keeps it out of
  // flex/grid gaps while it has nothing to say.
  if (gate.request === null) return <div role="status" className="empty:sr-only" />
  const { estimate } = gate
  const notice = gate.block ? (
    <UsageBlockedNotice
      block={gate.block}
      audience={audience}
      paths={paths}
      managedByName={managedByName}
      headingLevel={headingLevel}
      live={gate.blockSource === "start" ? "alert" : "status"}
      onRetry={gate.retry}
    />
  ) : null
  // A 402 from the start action is an alert and sits outside the polite region; everything else
  // updates inside one persistent status region so changes are announced.
  if (notice && gate.blockSource === "start") return notice
  let content: ReactNode
  if (notice) {
    content = notice
  } else if (estimate.isPending || isRecheckingBlock(estimate.data, estimate.isFetching)) {
    content = <p className="m-0 text-body-sm text-on-surface-variant">Working out the cost…</p>
  } else if (estimate.isError || !estimate.data) {
    content = (
      <p className="m-0 text-body-sm text-on-surface-variant">
        Couldn't estimate the cost right now. You can still start: you're only charged what the job actually costs.
      </p>
    )
  } else {
    const data = estimate.data
    // A free action (range 0 to 0, e.g. a seeded no-cost action) has no cost to promise: say nothing.
    const free = data.low === 0 && data.high === 0
    const ownPayer = data.payer === "allowance" || data.payer === "credits"
    content = free ? null : (
      <p data-testid="estimate-range" className="m-0 text-body-sm text-on-surface-variant">
        Estimated cost: <span className="text-data-sm text-on-surface">{estimateSentence(data)}</span>. You're
        charged the actual cost when it finishes.
        {subjectUnknown && ownPayer && audience === "student" ? " If a teacher's seat covers this paper's subject, the seat pays first." : null}
      </p>
    )
  }
  return <div role="status" className="empty:sr-only">{content}</div>
}

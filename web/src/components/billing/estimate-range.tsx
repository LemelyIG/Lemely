import type { Audience } from "@/lib/billingTypes"
import { estimateSentence } from "@/lib/billingFormat"
import type { BillingPaths } from "@/lib/billingPaths"
import type { MeteredGate } from "@/lib/meteredGate"
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
}: {
  gate: MeteredGate
  audience: Audience
  paths: BillingPaths | null
  managedByName: string | null
  subjectUnknown?: boolean
}) {
  if (gate.request === null) return null
  if (gate.block) {
    return <UsageBlockedNotice block={gate.block} audience={audience} paths={paths} managedByName={managedByName} />
  }
  const { estimate } = gate
  if (estimate.isPending) {
    return (
      <p role="status" className="m-0 text-body-sm text-on-surface-variant">
        Working out the cost…
      </p>
    )
  }
  if (estimate.isError || !estimate.data) {
    return (
      <p className="m-0 text-body-sm text-on-surface-variant">
        Couldn't estimate the cost right now. You can still start: you're only charged what the job actually costs.
      </p>
    )
  }
  const data = estimate.data
  const ownPayer = data.payer === "allowance" || data.payer === "credits"
  return (
    <p data-testid="estimate-range" className="m-0 text-body-sm text-on-surface-variant">
      Estimated cost: <span className="text-data-sm text-on-surface">{estimateSentence(data)}</span>. You're
      charged the actual cost when it finishes.
      {subjectUnknown && ownPayer ? " If a teacher's seat covers this paper's subject, the seat pays first." : null}
    </p>
  )
}

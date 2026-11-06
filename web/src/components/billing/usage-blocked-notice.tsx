import type { ReactNode } from "react"
import { Info } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import type { Audience } from "@/lib/billingTypes"
import type { BillingPaths } from "@/lib/billingPaths"
import { usageBlockCopy, type UsageBlock } from "@/lib/usageBlock"

/*
 * What a blocked metered action says, and the one next step it offers (spec §2.4, 402
 * reasons). `role="alert"` because it replaces an action the user just tried or was about to
 * try. Neutral tone: a missing balance is not an error in the user's work.
 */

const LINK =
  "inline-flex items-center rounded-button px-4 py-2 text-label font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"

export function UsageBlockedNotice({
  block,
  audience,
  paths,
  managedByName,
}: {
  block: UsageBlock
  audience: Audience
  paths: BillingPaths | null
  managedByName: string | null
}) {
  const copy = usageBlockCopy(block.reason, audience)
  let next: ReactNode = null
  if (copy.next === "ask_teacher") {
    next = <p className="m-0 text-body-sm text-on-surface">Ask your lead teacher to raise it.</p>
  } else if (managedByName) {
    next = <p className="m-0 text-body-sm text-on-surface">Ask {managedByName} to add credits.</p>
  } else if (paths && copy.next === "buy_credits") {
    next = (
      <div className="flex flex-wrap gap-2">
        <Link to={paths.packs} className={`${LINK} bg-primary text-on-primary hover:bg-primary-hover`}>
          Buy credits
        </Link>
        {block.reason === "usage_limit_reached" ? (
          <Link to={paths.plans} className={`${LINK} bg-primary-container text-on-primary-container`}>
            See plans
          </Link>
        ) : null}
      </div>
    )
  } else if (paths && copy.next === "see_plans") {
    next = (
      <Link to={paths.plans} className={`${LINK} self-start bg-primary text-on-primary hover:bg-primary-hover`}>
        See plans
      </Link>
    )
  }
  return (
    <div
      role="alert"
      data-testid="usage-blocked-notice"
      data-reason={block.reason}
      className="flex items-start gap-3 rounded-lg bg-surface-container-high p-4 text-on-surface"
    >
      <Info size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-on-surface-variant" />
      <div className="flex flex-col gap-2">
        <h3 className="m-0 text-body-md font-semibold">{copy.title}</h3>
        <p className="m-0 text-body-sm text-on-surface-variant">{copy.body}</p>
        {next}
      </div>
    </div>
  )
}

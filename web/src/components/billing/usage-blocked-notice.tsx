import { createElement, type ReactNode } from "react"
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
  headingLevel = 3,
  live = "alert",
  onRetry,
}: {
  block: UsageBlock
  audience: Audience
  paths: BillingPaths | null
  managedByName: string | null
  /** Heading level to fit the surrounding outline. */
  headingLevel?: 2 | 3 | 4
  /** `alert` for a 402 the user just hit; `status` (polite) for a block read off the estimate. */
  live?: "alert" | "status"
  /** Offers "Try again" once the cause may be fixed (credits bought in another tab). */
  onRetry?: () => void
}) {
  const copy = usageBlockCopy(block.reason, audience)
  let next: ReactNode = null
  if (copy.next === "ask_teacher") {
    next = <p className="m-0 text-body-sm text-on-surface">Ask your lead teacher to raise it.</p>
  } else if (managedByName) {
    next = <p className="m-0 text-body-sm text-on-surface">
        Ask {managedByName} to {block.reason === "no_active_plan" ? "choose a plan" : "add credits"}.
      </p>
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
      role={live}
      data-testid="usage-blocked-notice"
      data-reason={block.reason}
      className="flex items-start gap-3 rounded-lg bg-surface-container-high p-4 text-on-surface"
    >
      <Info size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-on-surface-variant" />
      <div className="flex flex-col gap-2">
        {createElement(`h${headingLevel}`, { className: "m-0 text-body-md font-semibold" }, copy.title)}
        <p className="m-0 text-body-sm text-on-surface-variant">{copy.body}</p>
        {next}
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="self-start rounded-button px-2 py-1 text-label font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"
          >
            Try again
          </button>
        ) : null}
      </div>
    </div>
  )
}

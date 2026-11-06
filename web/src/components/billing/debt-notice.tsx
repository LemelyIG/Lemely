import { Warning } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import type { Audience } from "@/lib/billingTypes"
import { debtSentence } from "@/lib/usageMeterModel"

/*
 * Debt (spec §2.4, §5.8): a job that overran the balance leaves the account negative, and new
 * jobs on that balance wait until the next grant repays it. A neutral warning, not crimson
 * (PRODUCT.md: students under stress get amber/neutral, never red-heavy states), not gold
 * (nothing here was earned).
 */

export function DebtNotice({
  debtUnits,
  audience,
  buyHref,
}: {
  debtUnits: number
  audience: Audience
  buyHref: string | null
}) {
  const sentence = debtSentence(debtUnits, audience)
  /* The status wrapper stays mounted so debt appearing later is announced (a live region
     inserted together with its content is often skipped by screen readers). */
  return (
    <div role="status">
      {sentence === null ? null : (
        <div className="flex items-start gap-3 rounded-lg bg-surface-container-high p-4 text-on-surface">
          <Warning size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-on-surface-variant" />
          <div className="flex flex-col gap-2">
            <p className="m-0 text-body-sm">{sentence}</p>
            {buyHref ? (
              <Link
                to={buyHref}
                className="self-start text-body-sm font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11 pointer-coarse:inline-flex pointer-coarse:items-center"
              >
                Buy credits
              </Link>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
/* Neutral surface and neutral icon, like DebtNotice: a price change is news, not an error and not an achievement. */
import { Info } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import type { PriceChangeNotice } from "@/lib/priceChange"

/*
 * The payer's notice that the plan's terms are changing (UD13-A): the new price and date first,
 * what else changes under it, and the way out. A teacher whose team is larger than the new plan
 * is told how many students to remove, before the date. The way out is cancelling at period end,
 * or, when the plan ends instead of moving, subscribing again.
 */

const ACTION =
  "inline-flex items-center self-start rounded-sm bg-transparent p-0 text-body-sm font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"

export function PriceChangeBanner({
  notice,
  plansHref,
  teamHref,
  onCancel,
}: {
  notice: PriceChangeNotice
  plansHref: string
  teamHref: string | null
  onCancel: (() => void) | null
}) {
  return (
    <section aria-labelledby="price-change-heading" className="flex items-start gap-3 rounded-lg bg-surface-container-high p-4 text-on-surface">
      <Info size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-on-surface-variant" />
      <div className="flex min-w-0 flex-col gap-2">
        <h2 id="price-change-heading" className="m-0 text-body-md font-medium">
          {notice.heading}
        </h2>
        {notice.details.length > 0 ? (
          <ul className="m-0 flex list-none flex-col gap-0.5 p-0 text-body-sm text-on-surface-variant">
            {notice.details.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        ) : null}
        {notice.seats ? (
          <p className="m-0 text-body-sm font-medium text-on-surface">
            Remove {notice.seats.remove} {notice.seats.remove === 1 ? "student" : "students"} from your team
            {notice.seats.before ? ` before ${notice.seats.before}` : ""}. The new plan has {notice.seats.capacity} seats.
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
          {notice.variant !== "move" ? (
            <Link to={plansHref} className={ACTION}>
              See plans
            </Link>
          ) : null}
          {notice.seats && teamHref ? (
            <Link to={teamHref} className={ACTION}>
              Manage seats
            </Link>
          ) : null}
          {notice.canCancel && onCancel ? (
            <button type="button" onClick={onCancel} className={ACTION}>
              Cancel at period end
            </button>
          ) : null}
        </div>
      </div>
    </section>
  )
}

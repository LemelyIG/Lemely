import { Link } from "react-router-dom"
import type { CreditBalance } from "@/lib/billingTypes"
import { creditExpiryLines } from "@/lib/usageMeterModel"

/*
 * Credits are an abstract balance with an expiry breakdown (spec §2.1). Purchased credits
 * expire 12 months after purchase; signup credits for teachers after 30 days. Lines within
 * 30 days of expiry are marked so a payer can spend them first.
 */

export function CreditBalanceCard({
  credits,
  now,
  buyHref,
}: {
  credits: CreditBalance
  now: Date
  buyHref: string | null
}) {
  const lines = creditExpiryLines(credits.buckets, now)
  return (
    <section
      aria-labelledby="credit-balance-heading"
      className="flex flex-col gap-3 rounded-lg border border-outline-variant bg-surface-container-lowest p-5"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="credit-balance-heading" className="m-0 text-display-sm text-on-surface">
          Credits
        </h2>
        <span className="text-data-md text-on-surface" aria-label={`${credits.total} credits`}>
          {new Intl.NumberFormat().format(credits.total)}
        </span>
      </div>
      {lines.length === 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="m-0 text-body-sm text-on-surface-variant">No credits yet.</p>
          {buyHref ? (
            <Link
              to={buyHref}
              className="text-body-sm font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11 pointer-coarse:inline-flex pointer-coarse:items-center"
            >
              Buy credits
            </Link>
          ) : null}
        </div>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {lines.map((line) => (
            <li key={line.key} className="flex items-center justify-between gap-3 text-body-sm text-on-surface">
              <span>{line.label}</span>
              {line.soon ? (
                <span className="rounded-pill bg-surface-container-high px-2.5 py-0.5 text-body-sm text-on-surface">
                  Expires soon
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

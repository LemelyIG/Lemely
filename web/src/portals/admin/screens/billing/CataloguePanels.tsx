/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import type { ReactNode } from "react"
import { formatUtc } from "@/lib/adminBillingModel"
import { MARKET_ATTRIBUTION, marketComparison, marketLine } from "@/lib/adminRatesModel"
import type { MarketReference } from "@/lib/billingTypes"

/* Pieces the catalogue's panels share: the titled section and the empty line. */

export function Section({ title, hint, action, children }: { title: string; hint?: string; action: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="m-0 text-display-sm text-on-surface">{title}</h2>
          {hint ? <p className="m-0 max-w-prose text-body-sm text-on-surface-variant">{hint}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 rounded-lg border border-dashed border-outline-variant px-4 py-6 text-body-sm text-on-surface-variant">{children}</p>
  )
}

/** "Changed 12 Nov 2026, 09:30 UTC by 3f2a91c4": the server names the admin by id. */
export function ChangedBy({ at, by }: { at: string; by: string | null }) {
  return (
    <span className="text-body-sm text-on-surface-variant">
      Changed {formatUtc(at)}
      {by ? (
        <>
          {" "}
          by <span className="text-data-sm" title={by}>{by.slice(0, 8)}</span>
        </>
      ) : null}
    </span>
  )
}

/**
 * A muted market-rate hint under a value. Shows nothing without a reading. It only reads: no
 * button, no value it could change. The attribution link is the feed's term of use; each panel
 * renders one hint, so one link.
 */
export function MarketNote({ reference, yours }: { reference: MarketReference | null | undefined; yours?: string | null }) {
  if (!reference) return null
  const note = yours === undefined ? null : marketComparison(yours, reference)
  return (
    <div className="mt-1 flex flex-col gap-0.5 text-body-sm text-on-surface-variant">
      <span>
        {marketLine(reference)}
        {note ? `. ${note}` : ""}
      </span>
      <a href={MARKET_ATTRIBUTION.href} target="_blank" rel="noopener noreferrer" className="w-fit text-body-sm underline underline-offset-2">
        {MARKET_ATTRIBUTION.text}
      </a>
    </div>
  )
}

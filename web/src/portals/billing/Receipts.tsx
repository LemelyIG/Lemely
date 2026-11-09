/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* A refund is named, never priced (M9); empty state offers the one way back. Row layout is the same card-per-record shape as usage history. */
import { Link } from "react-router-dom"
import { buttonVariants } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import { billingPaths } from "@/lib/billingPaths"
import { useReceipts } from "@/lib/hooks/useBillingApi"
import { purposeLabel, receiptStatusText } from "@/lib/usageHistoryModel"
import { OwnAccountNote } from "@/components/acting/own-account-note"

/*
 * Receipts exist only for real money (spec §2.5). A `paid` payment is the receipt; the payer
 * sees them, so a parent's list spans every child they pay for. M9: a receipt carries no card,
 * order id or refunded amount, so a refund is named ("Refunded"), never priced.
 */

export function ReceiptsView({ backHref, backLabel = "Back to plan and billing" }: { backHref: string; backLabel?: string }) {
  const receipts = useReceipts()
  return (
    <div className="flex flex-col gap-6">
      <h1 className="m-0 text-display-md text-on-surface">Receipts</h1>
      <QueryState
        query={receipts}
        skeleton={<ListSkeleton />}
        error={{ heading: "Couldn't load your receipts" }}
        isEmpty={(d) => d.receipts.length === 0}
        empty={
          <EmptyState kicker={null} heading="No receipts yet." body="Payments for plans, seats and credit packs appear here.">
            <Link to={backHref} className={buttonVariants({ variant: "secondary" })}>
              {backLabel}
            </Link>
          </EmptyState>
        }
      >
        {(d) => (
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {d.receipts.map((r) => {
              const refund = receiptStatusText(r)
              return (
                <li
                  key={r.paymentId}
                  className="flex flex-col gap-1 rounded-lg border border-outline-variant bg-surface-container-lowest p-4"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                    <span className="text-body-md font-semibold text-on-surface">{r.description}</span>
                    <span className="text-data-md text-on-surface">{formatMoney(r.amountMinor, r.currency)}</span>
                  </div>
                  <p className="m-0 text-body-sm text-on-surface-variant">
                    {purposeLabel(r.purpose)} · {formatBillingDate(r.paidAt)}
                  </p>
                  {refund ? <p className="m-0 text-body-sm font-medium text-on-surface">{refund}</p> : null}
                </li>
              )
            })}
          </ul>
        )}
      </QueryState>
    </div>
  )
}

export function StudentReceipts() {
  return <ReceiptsView backHref={billingPaths({ role: "student" }).overview} />
}

export function TeacherReceipts() {
  return (
    <>
      <OwnAccountNote />
      <ReceiptsView backHref={billingPaths({ role: "teacher" }).overview} />
    </>
  )
}

/** All of a parent's receipts, across children: receipts belong to the payer. */
export function ParentReceipts() {
  return <ReceiptsView backHref="/parent" backLabel="Back to your children" />
}

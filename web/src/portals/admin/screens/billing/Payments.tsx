/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { Warning } from "@phosphor-icons/react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Select } from "@/components/ui/select"
import { ErrorState } from "@/components/ui/state-views"
import { formatUtc, humanize, isForbidden, refundOutcome } from "@/lib/adminBillingModel"
import {
  PAYMENT_STATUS_OPTIONS,
  PROBLEM_SECTIONS,
  QUEUE_REFUND_CURRENCY,
  canReconcile,
  paymentTone,
  problemCount,
  reconcileNotice,
  sectionCount,
  type ProblemSection,
} from "@/lib/adminOpsModel"
import { formatMoney } from "@/lib/billingFormat"
import type { AdminPaymentRow, PaymentStatus, ProblemQueue } from "@/lib/billingTypes"
import { useAdminPayments, useProblemQueue, useReconcilePayment } from "@/lib/hooks/useAdminBillingApi"
import { cn } from "@/lib/utils"
import { PaymentActions, RefundHistory } from "./PaymentActions"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/*
 * Payments and the problem queue (spec §8.3). The queue comes first because it is the part an
 * admin opens this page for; the full list sits under it with a status filter.
 *
 * Reconcile asks Paymob's transaction inquiry what really happened and applies it. It never
 * charges, so it carries no retry guard: asking twice is the same question. The hook refetches
 * every billing read on any outcome, so a refused or dropped request cannot leave a stale row.
 *
 * An unknown Paymob outcome is never worded as a failure (R20b): a payment Paymob has not
 * answered stays pending, and a refund with no answer reads "outcome unknown".
 */

const LIST = "m-0 flex list-none flex-col divide-y divide-outline-variant overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest p-0"
const short = (id: string) => id.slice(0, 8)

/** Another user as a link to their billing view; payments carry ids, not names (M9). */
function UserRef({ id }: { id: string }) {
  return (
    <Link to={`/platform/billing/customers/${id}`} title={id} className="text-data-sm text-primary underline underline-offset-2">
      {short(id)}
    </Link>
  )
}

function PaymentRow({ p, listed, onReconcile }: { p: AdminPaymentRow; listed: boolean; onReconcile: (p: AdminPaymentRow) => void }) {
  return (
    <li className="flex flex-col gap-3 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="m-0 flex flex-wrap items-center gap-2 text-body-md font-medium text-on-surface">
            {humanize(p.purpose)}
            <Badge tone={paymentTone(p.status)}>{humanize(p.status)}</Badge>
          </p>
          <p className="m-0 text-body-sm text-on-surface-variant">
            <span className="whitespace-nowrap">{formatUtc(p.createdAt)}</span> · order <span className="text-data-sm">{p.paymobOrderId ?? "—"}</span>
            {listed ? (
              <>
                {" "}
                · transaction <span className="text-data-sm">{p.paymobTxnId ?? "—"}</span>
              </>
            ) : null}
          </p>
          <p className="m-0 text-body-sm text-on-surface-variant">
            {p.payerUserId === p.beneficiaryUserId ? (
              <>
                Payer and beneficiary <UserRef id={p.payerUserId} />
              </>
            ) : (
              <>
                Payer <UserRef id={p.payerUserId} /> · beneficiary <UserRef id={p.beneficiaryUserId} />
              </>
            )}
          </p>
        </div>
        <p className="m-0 text-start sm:text-end">
          <span className="block text-data-md text-on-surface">{formatMoney(p.amountMinor, p.currency)}</span>
          {p.refundedMinor > 0 ? <span className="block text-body-sm text-on-surface-variant">refunded {formatMoney(p.refundedMinor, p.currency)}</span> : null}
        </p>
      </div>
      <div className="flex flex-wrap gap-2 empty:hidden">
        {canReconcile(p.status) ? (
          <Button size="sm" variant="secondary" onClick={() => onReconcile(p)} aria-label={`Reconcile ${p.id}`}>
            Reconcile
          </Button>
        ) : null}
        {listed ? <PaymentActions payment={p} /> : null}
      </div>
      {listed ? <RefundHistory payment={p} /> : null}
    </li>
  )
}

function Group({ section, count, children }: { section: ProblemSection; count: number; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-0.5">
        <h3 className="m-0 flex items-baseline gap-2 text-body-lg font-semibold text-on-surface">
          {section.label}
          <span className="text-data-md font-normal text-on-surface-variant">{count}</span>
        </h3>
        <p className="m-0 max-w-prose text-body-sm text-on-surface-variant">{section.hint}</p>
      </div>
      {children}
    </div>
  )
}

function Queue({ q, onReconcile }: { q: ProblemQueue; onReconcile: (p: AdminPaymentRow) => void }) {
  return (
    <div className="flex flex-col gap-6">
      {PROBLEM_SECTIONS.map((section) => {
        const count = sectionCount(q, section.key)
        if (count === 0) return null
        if (section.key === "hmacFailures") {
          return (
            <Group key={section.key} section={section} count={count}>
              <p className="m-0 text-body-sm text-on-surface-variant">
                {q.hmacFailures24h} in the last 24 hours{q.hmacFailures.length < count ? `. Showing the latest ${q.hmacFailures.length}.` : "."}
              </p>
              {q.hmacFailures.length > 0 ? (
                <ul className={LIST}>
                  {q.hmacFailures.map((w) => (
                    <li key={w.id} className="flex flex-col gap-1 px-4 py-3 text-body-sm">
                      <span className="font-medium text-on-surface">{humanize(w.kind)} callback</span>
                      <span className="text-on-surface">{w.reason}</span>
                      <span className="text-on-surface-variant">
                        <span className="text-data-sm">{w.remoteAddr ?? "—"}</span> · {formatUtc(w.receivedAt)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </Group>
          )
        }
        if (section.key === "refundsNeedingAttention") {
          return (
            <Group key={section.key} section={section} count={count}>
              <ul className={LIST}>
                {q.refundsNeedingAttention.map((r) => {
                  const o = refundOutcome(r, QUEUE_REFUND_CURRENCY)
                  return (
                    <li key={r.id} className="flex items-start gap-2 px-4 py-3 text-body-sm">
                      {o.tone === "attention" ? <Warning size={16} aria-hidden className="mt-0.5 shrink-0 text-on-surface-variant" /> : null}
                      <span className="flex min-w-0 flex-col gap-0.5">
                        <span className={cn("font-medium", o.tone === "error" ? "text-error" : "text-on-surface")}>{o.label}</span>
                        <span className="text-on-surface-variant">{o.detail}</span>
                        <span className="text-on-surface-variant">
                          Reason: {r.reason} · updated {formatUtc(r.updatedAt)}
                        </span>
                      </span>
                    </li>
                  )
                })}
              </ul>
            </Group>
          )
        }
        return (
          <Group key={section.key} section={section} count={count}>
            <ul className={LIST}>
              {q[section.key as "mismatches" | "stalePending" | "missingCallbacks"].map((p) => (
                <PaymentRow key={p.id} p={p} listed={false} onReconcile={onReconcile} />
              ))}
            </ul>
          </Group>
        )
      })}
    </div>
  )
}

export function Payments() {
  const [status, setStatus] = useState<PaymentStatus | null>(null)
  const payments = useAdminPayments(status)
  const problems = useProblemQueue()
  const reconcile = useReconcilePayment()
  const [reconciling, setReconciling] = useState<AdminPaymentRow | null>(null)

  if ((problems.status === "error" && isForbidden(problems.error)) || (payments.status === "error" && isForbidden(payments.error))) {
    return <ErrorState kicker={null} heading="You can't open billing payments" body="Billing is for platform admins. Ask one to look at this." />
  }

  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2 className="m-0 text-display-sm text-on-surface">Problem queue</h2>
          <p className="m-0 text-body-sm text-on-surface-variant">Refreshes every minute.</p>
        </div>
        {/* Present from the first render, so the answer to a reconcile is announced when it arrives. */}
        <div role="status" className="empty:hidden">
          {reconcile.data ? <p className="m-0 rounded-md bg-surface-container-low px-3 py-2 text-body-sm text-on-surface">{reconcileNotice(reconcile.data)}</p> : null}
        </div>
        <QueryState
          query={problems}
          skeleton={<ListSkeleton rows={2} />}
          error={{ heading: "Couldn't load the problem queue", compact: true }}
          isEmpty={(q) => problemCount(q) === 0}
          empty={<p className="m-0 text-body-md text-on-surface-variant">No payment problems right now.</p>}
        >
          {(q) => <Queue q={q} onReconcile={setReconciling} />}
        </QueryState>
      </section>

      <section className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="m-0 text-display-sm text-on-surface">All payments</h2>
          <div className="w-full sm:w-56">
            <Select label="Status" value={status ?? ""} onChange={(e) => setStatus((e.target.value || null) as PaymentStatus | null)}>
              {PAYMENT_STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <QueryState
          query={payments}
          skeleton={<ListSkeleton />}
          error={{ heading: "Couldn't load payments" }}
          isEmpty={(d) => d.pages.every((pg) => pg.items.length === 0)}
          empty={<p className="m-0 text-body-md text-on-surface-variant">{status ? "No payments with this status." : "No payments yet."}</p>}
        >
          {(d) => (
            <>
              <ul className={LIST}>
                {d.pages
                  .flatMap((pg) => pg.items)
                  .map((p) => (
                    <PaymentRow key={p.id} p={p} listed onReconcile={setReconciling} />
                  ))}
              </ul>
              {payments.hasNextPage ? (
                <div>
                  <Button variant="secondary" loading={payments.isFetchingNextPage} onClick={() => void payments.fetchNextPage()}>
                    Load more
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </QueryState>
      </section>

      {reconciling ? (
        <ReasonedFormDialog
          open
          onClose={() => setReconciling(null)}
          title="Reconcile payment"
          fields={[]}
          initial={{}}
          submitLabel="Reconcile"
          mutation={reconcile}
          toBody={(_v, r) => ({ id: reconciling.id, body: { reason: r } })}
          reload="Reload this page"
          note={
            <p className="m-0 text-body-sm text-on-surface">
              Order {reconciling.paymobOrderId ?? reconciling.id}, {formatMoney(reconciling.amountMinor, reconciling.currency)}, {humanize(reconciling.status).toLowerCase()}. This asks Paymob for the
              payment's real state and records it. Nothing is charged.
            </p>
          }
        />
      ) : null}
    </div>
  )
}

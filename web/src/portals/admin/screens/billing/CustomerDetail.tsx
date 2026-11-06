/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useId, useState, type ReactNode } from "react"
import { Link, useParams } from "react-router-dom"
import { Badge, type BadgeTone } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { ErrorState } from "@/components/ui/state-views"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import {
  ADJUST_FIELDS,
  CANCEL_FIELDS,
  EXTEND_FIELDS,
  FORGIVE_FIELDS,
  GRANT_FIELDS,
  activatableTiers,
  activationBody,
  activationFields,
  adjustBody,
  cancelBody,
  extendBody,
  forgiveBody,
  grantBody,
  humanize,
  isAmbiguousFailure,
  isForbidden,
} from "@/lib/adminBillingModel"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import type { AdminMember, AdminPaymentRow, AdminSubscription, PaymentStatus, SubscriptionStatus } from "@/lib/billingTypes"
import {
  useAdjustBalance,
  useAdminCancelSubscription,
  useAdminCatalogue,
  useCustomer,
  useExtendSubscription,
  useForgiveDebt,
  useGrantCredits,
  useManualActivation,
} from "@/lib/hooks/useAdminBillingApi"
import { randomUuid } from "@/lib/uuid"
import { PaymentActions, RefundHistory } from "./PaymentActions"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/*
 * One customer's whole billing picture (plan 07 `CustomerDetailDTO`) and every admin money
 * action (spec §8.2). Each action carries a reason the server audits. Admins see unit counts
 * here; nothing on this screen is shown to customers.
 *
 * Grant and adjust mint one `requestId` per opened dialog, so a double submit is one write.
 * Forgive-debt has no idempotency key: its dialog ignores a second submit while the first is
 * pending, and nothing here ever retries it.
 */

const n = (v: number) => new Intl.NumberFormat("en-US").format(v)
const d = (iso: string | null) => (iso ? formatBillingDate(iso) : "—")
const short = (id: string) => id.slice(0, 8)
const LIVE = new Set<SubscriptionStatus>(["pending_first_payment", "active", "past_due"])

const SUB_TONE: Record<SubscriptionStatus, BadgeTone> = {
  active: "ok",
  pending_first_payment: "info",
  past_due: "warn",
  cancelled: "sage",
  expired: "sage",
  inactive: "sage",
  rejected: "sage",
}
const PAY_TONE: Record<PaymentStatus, BadgeTone> = {
  paid: "ok",
  created: "info",
  pending: "info",
  partially_refunded: "info",
  refunded: "sage",
  voided: "sage",
  failed: "err",
  failed_mismatch: "err",
}

function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="m-0 text-display-sm text-on-surface">
          {title}
        </h3>
        {action ? <div className="flex flex-wrap gap-2">{action}</div> : null}
      </div>
      {children}
    </section>
  )
}

/**
 * After an ambiguous failure (dropped connection, 5xx) of a write that carries no idempotency key,
 * returns why Submit is blocked until the customer has been refetched, so the figures in the
 * dialog are fresh before any retry. The hook invalidates the customer on error; this waits for
 * that refetch to land. A refusal (4xx) changed nothing and never blocks.
 */
function useRetryGuard(
  mutation: { isError: boolean; error: unknown },
  customer: { dataUpdatedAt: number; isError: boolean },
): string | null {
  const [seen, setSeen] = useState<unknown>(null)
  const [since, setSince] = useState<number | null>(null)
  if (mutation.isError && mutation.error !== seen && isAmbiguousFailure(mutation.error)) {
    setSeen(mutation.error)
    setSince(customer.dataUpdatedAt)
  }
  if (since === null || customer.dataUpdatedAt > since) return null
  return customer.isError
    ? "Couldn't reload this customer, so the result of the last attempt is unknown. Reload this page before trying again."
    : "The last attempt may have gone through. Reloading this customer before you can try again."
}

const Empty = ({ children }: { children: ReactNode }) => <p className="m-0 text-body-sm text-on-surface-variant">{children}</p>

/** Another user, as a link to their own billing view. Ids stand in for names on payments (M9). */
const UserLink = ({ id }: { id: string }) => (
  <Link to={`/platform/billing/customers/${id}`} title={id} className="text-data-sm text-primary underline underline-offset-2">
    {short(id)}
  </Link>
)

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-1 bg-surface-container-lowest px-4 py-3">
      <dt className="text-body-sm text-on-surface-variant">{label}</dt>
      <dd className="m-0 text-data-lg text-on-surface">{n(value)}</dd>
    </div>
  )
}

function Members({ title, rows }: { title: string; rows: AdminMember[] }) {
  if (rows.length === 0) return null
  return (
    <Panel title={title}>
      <ul className="m-0 flex list-none flex-col gap-1 p-0 text-body-sm text-on-surface">
        {rows.map((m) => (
          <li key={m.memberId}>
            <Link to={`/platform/billing/customers/${m.userId}`} className="text-primary underline underline-offset-2">
              {m.email}
            </Link>{" "}
            · {m.kind}
            {m.rolePreset ? ` (${m.rolePreset})` : ""} · {m.status}
            {m.leavesAt ? ` until ${d(m.leavesAt)}` : ""}
          </li>
        ))}
      </ul>
    </Panel>
  )
}

function Subscription({
  sub,
  onExtend,
  onCancel,
}: {
  sub: AdminSubscription
  onExtend: () => void
  onCancel: () => void
}) {
  const hintId = useId()
  const live = LIVE.has(sub.status)
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-outline-variant bg-surface-container-lowest p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="m-0 flex flex-wrap items-center gap-2 text-body-md font-semibold text-on-surface">
          {sub.planName}
          <Badge tone={SUB_TONE[sub.status]}>{humanize(sub.status)}</Badge>
          {sub.cancelAtPeriodEnd ? <Badge tone="warn">Ends at period end</Badge> : null}
          {sub.isManuallyActivated ? <Badge tone="sky">Complimentary</Badge> : null}
        </p>
        {live ? (
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={onExtend}
              disabled={!sub.isManuallyActivated}
              aria-describedby={sub.isManuallyActivated ? undefined : hintId}
            >
              Extend subscription
            </Button>
            <Button size="sm" variant="secondary" onClick={onCancel}>
              Cancel subscription
            </Button>
          </div>
        ) : null}
      </div>
      <p className="m-0 max-w-prose text-body-sm text-on-surface-variant">
        {d(sub.currentPeriodStart)} to {d(sub.currentPeriodEnd)}
        {sub.isManuallyActivated ? (
          " · no payment taken"
        ) : (
          <>
            {" "}
            · payer {sub.payerUserId ? <UserLink id={sub.payerUserId} /> : "—"} · Paymob <span className="text-data-sm">{sub.paymobSubscriptionId ?? "—"}</span>
          </>
        )}
        {sub.graceUntil ? ` · grace until ${d(sub.graceUntil)}` : ""}
      </p>
      {live && !sub.isManuallyActivated ? (
        <p id={hintId} className="m-0 max-w-prose text-body-sm text-on-surface-variant">
          Paymob bills this plan, so its period can't be extended here. Grant credits instead.
        </p>
      ) : null}
      {sub.periods.length > 0 ? (
        <ul className="m-0 flex list-none flex-col gap-1 p-0 text-body-sm text-on-surface-variant">
          {sub.periods.map((p) => (
            <li key={p.periodStart}>
              {d(p.periodStart)} to {d(p.periodEnd)}
              {p.paymentId ? ` · payment ${p.paymentId}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function PaymentItem({ p, customerId }: { p: AdminPaymentRow; customerId: string }) {
  return (
    <li className="flex flex-col gap-3 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="m-0 flex flex-wrap items-center gap-2 text-body-md font-medium text-on-surface">
            {humanize(p.purpose)}
            <Badge tone={PAY_TONE[p.status]}>{humanize(p.status)}</Badge>
          </p>
          <p className="m-0 text-body-sm text-on-surface-variant">
            {d(p.createdAt)} · Paymob order <span className="text-data-sm">{p.paymobOrderId ?? "—"}</span>
            {p.payerUserId !== customerId ? (
              <>
                {" "}
                · paid by <UserLink id={p.payerUserId} />
              </>
            ) : null}
          </p>
        </div>
        <p className="m-0 text-start sm:text-end">
          <span className="block text-data-md text-on-surface">{formatMoney(p.amountMinor, p.currency)}</span>
          {p.refundedMinor > 0 ? <span className="block text-body-sm text-on-surface-variant">refunded {formatMoney(p.refundedMinor, p.currency)}</span> : null}
        </p>
      </div>
      <div className="flex flex-wrap gap-2 empty:hidden">
        <PaymentActions payment={p} />
      </div>
      <RefundHistory payment={p} />
    </li>
  )
}

type Action =
  | { kind: "grant" | "adjust" | "forgive" | "activate" }
  | { kind: "extend" | "cancel"; subscriptionId: string }
  | null

export function CustomerDetail() {
  const { userId = "" } = useParams<{ userId: string }>()
  const customer = useCustomer(userId)
  const catalogue = useAdminCatalogue()
  const grant = useGrantCredits(userId)
  const adjust = useAdjustBalance(userId)
  const forgive = useForgiveDebt(userId)
  const activate = useManualActivation(userId)
  const extend = useExtendSubscription(userId)
  const cancel = useAdminCancelSubscription(userId)
  const [action, setAction] = useState<Action>(null)
  const forgiveBlocked = useRetryGuard(forgive, customer)
  const activateBlocked = useRetryGuard(activate, customer)
  const extendBlocked = useRetryGuard(extend, customer)
  const cancelBlocked = useRetryGuard(cancel, customer)
  const [notice, setNotice] = useState<string | null>(null)
  // One idempotency key per opened grant/adjust dialog (07 `requestId`), minted when it opens.
  const [requestId, setRequestId] = useState("")
  const open = (next: NonNullable<Action>) => {
    setRequestId(randomUuid())
    setAction(next)
  }
  const close = () => setAction(null)
  const saved = (what: string) => () => setNotice(`${what} The change and your reason are in the audit log.`)
  const reload = "Reload this page"

  if (customer.status === "error" && isForbidden(customer.error)) {
    return <ErrorState kicker={null} heading="You can't open billing customers" body="Billing is for platform admins. Ask one to look this customer up." />
  }

  return (
    <QueryState query={customer} skeleton={<PageHeaderSkeleton />} error={{ heading: "Couldn't load this customer" }}>
      {(c) => {
        const tiers = activatableTiers(catalogue.data?.tiers ?? [], c.user.role)
        const sub = (id: string) => c.subscriptions.find((s) => s.id === id)
        return (
          <div className="flex flex-col gap-8">
            <header className="flex flex-col gap-2">
              <Link to="/platform/billing" className="w-fit text-body-sm text-primary underline-offset-2 hover:underline">
                All customers
              </Link>
              <h2 className="m-0 text-display-md text-on-surface">{c.user.displayName ?? c.user.email}</h2>
              <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-body-sm text-on-surface-variant">
                <span>{c.user.email}</span>
                <span aria-hidden>·</span>
                <span>{humanize(c.user.role)}</span>
                <span aria-hidden>·</span>
                <span>joined {d(c.user.createdAt)}</span>
                <span aria-hidden>·</span>
                <span className="break-all text-data-sm">{c.user.id}</span>
              </p>
            </header>

            <div role="status" className={notice ? "rounded-md bg-surface-container-low px-4 py-3 text-body-sm text-on-surface" : "sr-only"}>
              {notice}
            </div>

            <Panel
              title="Balance"
              action={
                <>
                  <Button size="sm" variant="secondary" onClick={() => open({ kind: "grant" })}>
                    Grant credits
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => open({ kind: "adjust" })}>
                    Adjust balance
                  </Button>
                  {c.balance.outstandingDebt > 0 ? (
                    <Button size="sm" variant="secondary" onClick={() => open({ kind: "forgive" })}>
                      Forgive debt
                    </Button>
                  ) : null}
                </>
              }
            >
              <dl className="m-0 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-outline-variant bg-outline-variant md:grid-cols-4">
                <Stat label="Allowance available" value={c.balance.allowanceAvailable} />
                <Stat label="Credits available" value={c.balance.creditsAvailable} />
                <Stat label="Seat allowance available" value={c.balance.seatAvailable} />
                <Stat label="Outstanding debt" value={c.balance.outstandingDebt} />
              </dl>
              {c.grants.length === 0 ? (
                <Empty>No grants.</Empty>
              ) : (
                <Table density="operate" tabIndex={0} role="region" aria-label="Grants">
                  <caption className="sr-only">Grants</caption>
                  <THead>
                    <TR>
                      <TH>Kind</TH>
                      <TH numeric>Units</TH>
                      <TH numeric>Remaining</TH>
                      <TH numeric>Held</TH>
                      <TH>Expires</TH>
                      <TH>Seat</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {c.grants.map((g) => (
                      <TR key={g.id}>
                        <TD>
                          <span className="text-data-sm">{g.kind}</span>
                        </TD>
                        <TD numeric>{n(g.units)}</TD>
                        <TD numeric>{n(g.remaining)}</TD>
                        <TD numeric>{n(g.held)}</TD>
                        <TD className="whitespace-nowrap">{g.expiresAt ? d(g.expiresAt) : "Never"}</TD>
                        <TD>{g.teacherMemberId ? "Seat" : "—"}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
              {c.debts.length > 0 ? (
                <ul className="m-0 flex list-none flex-col gap-1 p-0 text-body-sm text-on-surface">
                  {c.debts.map((x) => (
                    <li key={x.id}>
                      {n(x.outstanding)} of {n(x.units)} outstanding{x.jobId ? ` from job ${x.jobId}` : ""}, {d(x.createdAt)}
                    </li>
                  ))}
                </ul>
              ) : null}
            </Panel>

            <Panel
              title="Subscriptions"
              action={
                <Button size="sm" variant="secondary" onClick={() => open({ kind: "activate" })} disabled={tiers.length === 0 || catalogue.isError}>
                  Activate manually
                </Button>
              }
            >
              {c.subscriptions.length === 0 ? <Empty>No subscription.</Empty> : null}
              {c.subscriptions.map((s) => (
                <Subscription
                  key={s.id}
                  sub={s}
                  onExtend={() => open({ kind: "extend", subscriptionId: s.id })}
                  onCancel={() => open({ kind: "cancel", subscriptionId: s.id })}
                />
              ))}
              {catalogue.isError ? (
                <Empty>Couldn't load plans. Reload this page.</Empty>
              ) : tiers.length === 0 ? (
                <Empty>{catalogue.isPending ? "Loading plans." : "No plan is on sale for this role, so manual activation is unavailable."}</Empty>
              ) : null}
            </Panel>

            <Panel title="Usage jobs">
              {c.usageJobs.length === 0 ? (
                <Empty>No usage yet.</Empty>
              ) : (
                <Table density="operate" tabIndex={0} role="region" aria-label="Usage jobs">
                  <caption className="sr-only">Usage jobs</caption>
                  <THead>
                    <TR>
                      <TH>Date</TH>
                      <TH>Action</TH>
                      <TH>Status</TH>
                      <TH numeric>Estimate</TH>
                      <TH numeric>Charged</TH>
                      <TH numeric>Cost (USD)</TH>
                      <TH>Versions</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {c.usageJobs.map((j) => (
                      <TR key={j.jobId} className="[&>td]:align-top">
                        <TD className="whitespace-nowrap">{d(j.createdAt)}</TD>
                        <TD>{j.action}</TD>
                        <TD>{humanize(j.status)}</TD>
                        <TD numeric>
                          {j.estimateLow}–{j.estimateHigh}
                        </TD>
                        <TD numeric className="whitespace-nowrap">
                          {j.charged ?? "—"}
                          {j.outsideRange || j.debtCreated ? (
                            <span className="block text-body-sm text-on-surface-variant">
                              {[j.outsideRange ? "Outside range" : "", j.debtCreated ? `${j.debtCreated} into debt` : ""].filter(Boolean).join(" · ")}
                            </span>
                          ) : null}
                        </TD>
                        <TD numeric>
                          <span className="text-data-sm">{j.actualCostUsd ?? "—"}</span>
                        </TD>
                        <TD>
                          <span className="text-data-sm">
                            rate {j.rateVersion} · est {j.estimatorVersion}
                          </span>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </Panel>

            <Panel title="Payments">
              {c.payments.length === 0 ? (
                <Empty>No payments.</Empty>
              ) : (
                <ul className="m-0 flex list-none flex-col divide-y divide-outline-variant overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest p-0">
                  {c.payments.map((p) => (
                    <PaymentItem key={p.id} p={p} customerId={c.user.id} />
                  ))}
                </ul>
              )}
            </Panel>

            <Members title="Seats" rows={c.seats} />
            <Members title="Assistants" rows={c.assistants} />
            <Members title="Seats with teachers" rows={c.seatedWith} />
            {c.parents.length > 0 || c.children.length > 0 ? (
              <Panel title="Family">
                <ul className="m-0 flex list-none flex-col gap-1 p-0 text-body-sm text-on-surface">
                  {c.parents.map((p) => (
                    <li key={p.userId}>
                      Parent: <Link to={`/platform/billing/customers/${p.userId}`} className="text-primary underline underline-offset-2">{p.displayName ?? p.email}</Link> · {p.email}
                    </li>
                  ))}
                  {c.children.map((p) => (
                    <li key={p.userId}>
                      Child: <Link to={`/platform/billing/customers/${p.userId}`} className="text-primary underline underline-offset-2">{p.displayName ?? p.email}</Link> · {p.email}
                    </li>
                  ))}
                </ul>
              </Panel>
            ) : null}
            {c.audit.length > 0 ? (
              <Panel title="Audit trail">
                <ul className="m-0 flex list-none flex-col gap-1 p-0 text-body-sm text-on-surface">
                  {c.audit.map((a) => (
                    <li key={a.id}>
                      {d(a.createdAt)} · {a.action} · {a.reason}
                    </li>
                  ))}
                </ul>
              </Panel>
            ) : null}

            {action?.kind === "grant" ? (
              <ReasonedFormDialog
                open
                onClose={close}
                title="Grant credits"
                fields={GRANT_FIELDS}
                initial={{ units: "", validDays: "365" }}
                submitLabel="Grant credits"
                mutation={grant}
                toBody={(v, r) => ({ id: userId, body: grantBody(v, r, requestId) })}
                onSaved={saved("Credits granted.")}
                reload={reload}
              />
            ) : null}
            {action?.kind === "adjust" ? (
              <ReasonedFormDialog
                open
                onClose={close}
                title="Adjust balance"
                fields={ADJUST_FIELDS}
                initial={{ units: "" }}
                submitLabel="Adjust balance"
                mutation={adjust}
                toBody={(v, r) => ({ id: userId, body: adjustBody(v, r, requestId) })}
                onSaved={saved("Balance adjusted.")}
                reload={reload}
              />
            ) : null}
            {action?.kind === "forgive" ? (
              <ReasonedFormDialog
                open
                onClose={close}
                title="Forgive debt"
                fields={FORGIVE_FIELDS}
                initial={{ units: "" }}
                submitLabel="Forgive debt"
                mutation={forgive}
                blocked={forgiveBlocked}
                toBody={(v, r) => ({ id: userId, body: forgiveBody(v, r) })}
                onSaved={saved("Debt forgiven.")}
                reload={reload}
                note={
                  <p className="m-0 text-body-sm text-on-surface">
                    {n(c.balance.outstandingDebt)} units are outstanding. Forgiving writes them off without a payment. If the connection drops, reload
                    to check the debt before trying again.
                  </p>
                }
              />
            ) : null}
            {action?.kind === "activate" ? (
              <ReasonedFormDialog
                open
                onClose={close}
                title="Activate manually"
                fields={activationFields(tiers)}
                initial={{ planTierId: tiers[0]?.id ?? "", periodDays: "30" }}
                submitLabel="Activate"
                mutation={activate}
                blocked={activateBlocked}
                toBody={(v, r) => ({ id: userId, body: activationBody(v, r) })}
                onSaved={saved("Plan activated.")}
                reload={reload}
                note={<p className="m-0 text-body-sm text-on-surface">For complimentary accounts. No payment is taken.</p>}
              />
            ) : null}
            {action?.kind === "extend" ? (
              <ReasonedFormDialog
                open
                onClose={close}
                title="Extend subscription"
                fields={EXTEND_FIELDS}
                initial={{ days: "7" }}
                submitLabel="Extend subscription"
                mutation={extend}
                blocked={extendBlocked}
                toBody={(v, r) => ({ id: action.subscriptionId, body: extendBody(v, r) })}
                onSaved={saved("Subscription extended.")}
                reload={reload}
                note={
                  <p className="m-0 text-body-sm text-on-surface">
                    The period now ends {d(sub(action.subscriptionId)?.currentPeriodEnd ?? null)}. Only complimentary plans can be extended.
                  </p>
                }
              />
            ) : null}
            {action?.kind === "cancel" ? (
              <ReasonedFormDialog
                open
                onClose={close}
                title="Cancel subscription"
                fields={CANCEL_FIELDS}
                initial={{ immediate: false }}
                submitLabel="Cancel subscription"
                mutation={cancel}
                blocked={cancelBlocked}
                toBody={(v, r) => ({ id: action.subscriptionId, body: cancelBody(v, r) })}
                onSaved={saved("Subscription cancelled.")}
                reload={reload}
                note={
                  <p className="m-0 text-body-sm text-on-surface">
                    By default access continues until {d(sub(action.subscriptionId)?.currentPeriodEnd ?? null)} and no further payment is taken.
                    {sub(action.subscriptionId)?.paymobSubscriptionId ? " Ending access now also cancels the plan on Paymob first." : ""}
                  </p>
                }
              />
            ) : null}
          </div>
        )
      }}
    </QueryState>
  )
}

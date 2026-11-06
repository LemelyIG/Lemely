import { useState, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { CreditBalanceCard } from "@/components/billing/credit-balance"
import { DebtNotice } from "@/components/billing/debt-notice"
import { UsageMeterCard } from "@/components/billing/usage-meter"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { formatBillingDate, formatMoney, intervalLabel, isLiveSubscription } from "@/lib/billingFormat"
import { billingPaths, type BillingScope } from "@/lib/billingPaths"
import type { Audience, BillingSummary } from "@/lib/billingTypes"
import { useBillingSummary, useCatalogue } from "@/lib/hooks/useBillingApi"
import { useUsageMeter } from "@/lib/hooks/useUsageApi"
import { CancelPlanDialog } from "./CancelPlanDialog"
import { PlanChangeDialog } from "./PlanChangeDialog"

/*
 * The billing page body shared by the student, teacher and parent-for-child screens, read from
 * `GET /billing/summary` (A5). The beneficiary sees plan, usage and balance; only the payer
 * (`canManage`) sees buy, change, cancel and receipts (spec §7 authorization).
 */

const TEXT_LINK =
  "inline-flex items-center rounded-sm font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"

function PlanCard({
  summary,
  audience,
  plansHref,
  onCancel,
}: {
  summary: BillingSummary
  audience: Audience
  plansHref: string
  onCancel: () => void
}) {
  const sub = summary.subscription
  const live = isLiveSubscription(sub?.status)
  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        <h2 className="m-0 text-display-sm text-on-surface">{live && sub ? sub.tier.name : "No plan"}</h2>
        {!live || !sub ? (
          <p className="m-0 text-body-md text-on-surface-variant">You're using credits only.</p>
        ) : (
          <>
            <p className="m-0 flex flex-wrap items-baseline gap-x-2">
              <span className="text-data-md text-on-surface">{formatMoney(sub.tier.priceMinor, sub.tier.currency)}</span>
              <span className="text-body-sm text-on-surface-variant">{intervalLabel(sub.tier.interval)}</span>
            </p>
            {sub.status === "pending_first_payment" ? (
              <p className="m-0 text-body-sm text-on-surface-variant">Waiting for the first payment to confirm.</p>
            ) : sub.cancelAtPeriodEnd && sub.currentPeriodEnd ? (
              <p className="m-0 text-body-sm text-on-surface-variant">
                Ends {formatBillingDate(sub.currentPeriodEnd)}. Usage comes from credits after that.
              </p>
            ) : sub.currentPeriodEnd ? (
              <p className="m-0 text-body-sm text-on-surface-variant">Renews {formatBillingDate(sub.currentPeriodEnd)}</p>
            ) : null}
            {sub.pendingTier && sub.currentPeriodEnd ? (
              <p className="m-0 text-body-sm text-on-surface-variant">
                Changes to {sub.pendingTier.name} on {formatBillingDate(sub.currentPeriodEnd)}
              </p>
            ) : null}
            {audience === "teacher" && summary.seats ? (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-body-sm text-on-surface">
                <span>
                  {summary.seats.used} of {summary.seats.capacity} seats used
                </span>
                <span className="text-on-surface-variant">
                  {sub.tier.includedSeats ?? 0} included, {sub.extraSeats} extra
                </span>
                <Link to="/teacher/team" className={TEXT_LINK}>
                  Manage seats
                </Link>
              </div>
            ) : null}
          </>
        )}
        {summary.canManage ? (
          <div className="flex flex-wrap gap-2 pt-1">
            <Link to={plansHref} className={buttonVariants({ variant: "primary" })}>
              {live ? "Change plan" : "See plans"}
            </Link>
            {live && sub && sub.status !== "pending_first_payment" && !sub.cancelAtPeriodEnd ? (
              <Button variant="ghost" onClick={onCancel}>
                Cancel plan
              </Button>
            ) : null}
          </div>
        ) : (
          <p className="m-0 text-body-sm text-on-surface-variant">{summary.managedByName ?? "Someone else"} manages this plan.</p>
        )}
      </CardBody>
    </Card>
  )
}

export function BillingOverview({
  scope,
  audience,
  beneficiaryId,
  heading,
  extra,
}: {
  scope: BillingScope
  audience: Audience
  beneficiaryId: string | null
  heading: string
  extra?: ReactNode
}) {
  const paths = billingPaths(scope)
  const summary = useBillingSummary(beneficiaryId)
  // Own seat meters only: `/usage/meter` serves the caller (M6), the summary carries none.
  const ownMeter = useUsageMeter()
  const catalogue = useCatalogue(audience)
  const [params, setParams] = useSearchParams()
  const [cancelOpen, setCancelOpen] = useState(false)
  const changeTo = params.get("change")
  const changeTier = catalogue.data?.tiers.find((t) => t.id === changeTo) ?? null
  const closeChange = () => {
    const next = new URLSearchParams(params)
    next.delete("change")
    setParams(next, { replace: true })
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="m-0 text-display-md text-on-surface">{heading}</h1>
      <QueryState query={summary} skeleton={<PageHeaderSkeleton />} error={{ heading: "Couldn't load your billing" }}>
        {(s) => {
          const sub = s.subscription
          const live = isLiveSubscription(sub?.status)
          const meter = beneficiaryId === null ? { ...s.meter, seats: ownMeter.data?.seats ?? [] } : s.meter
          return (
            <>
              {sub?.status === "past_due" ? (
                <div role="status" className="rounded-lg bg-surface-container-high p-4 text-body-sm text-on-surface">
                  Your last renewal didn't go through. Paymob is retrying, and your plan keeps working
                  {sub.graceUntil ? <> until {formatBillingDate(sub.graceUntil)}</> : null}. Check the card with your bank if it
                  keeps failing.
                </div>
              ) : null}
              {/* DebtNotice keeps an empty live region mounted so a later debt is announced; the
                  negative margin takes back the flex gap that empty region would otherwise add. */}
              <div className="has-[[role=status]:empty]:-mt-6">
                <DebtNotice debtUnits={meter.debtUnits} audience={audience} buyHref={s.canManage ? paths.packs : null} />
              </div>
              <PlanCard summary={s} audience={audience} plansHref={paths.plans} onCancel={() => setCancelOpen(true)} />
              <div className="grid gap-4 md:grid-cols-2">
                <UsageMeterCard meter={meter} />
                <CreditBalanceCard credits={meter.credits} now={new Date()} buyHref={s.canManage ? paths.packs : null} />
              </div>
              {extra}
              <nav aria-label="More billing" className="flex flex-wrap gap-x-6 gap-y-1 text-body-sm">
                {paths.history ? (
                  <Link to={paths.history} className={TEXT_LINK}>
                    Usage history
                  </Link>
                ) : null}
                {s.canManage ? (
                  <Link to={paths.receipts} className={TEXT_LINK}>
                    Receipts
                  </Link>
                ) : null}
              </nav>
              {live && sub && s.canManage ? (
                <>
                  <PlanChangeDialog
                    open={changeTier !== null && changeTier.id !== sub.tier.id}
                    onClose={closeChange}
                    subscription={sub}
                    tier={changeTier}
                    savedCard={s.savedCard}
                  />
                  <CancelPlanDialog open={cancelOpen} onClose={() => setCancelOpen(false)} subscription={sub} audience={audience} />
                </>
              ) : null}
            </>
          )
        }}
      </QueryState>
    </div>
  )
}

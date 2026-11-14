/* Hallmark · pre-emit critique: P4 H4 E4 S4 R3 V3 */
/* R3/V3: the plans grid and the credit-pack grid repeat the same 2/3-column card rhythm back to back, so the page reads as two copies of one template. A checkout failure is reported at the end of the section whose button was pressed. */
import { useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Check } from "@phosphor-icons/react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { PhoneEntryForm } from "@/components/phone-entry-form"
import { CardGridSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { formatCredits, formatMoney, intervalLabel } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { BillingPaths } from "@/lib/billingPaths"
import type { Audience, BillingInterval, CreditPack, PlanTier } from "@/lib/billingTypes"
import {
  clampExtraSeats,
  initialInterval,
  packCheckoutRequest,
  seatsIncludedLabel,
  startCheckoutRedirect,
  subscriptionCheckoutRequest,
  tiersForInterval,
} from "@/lib/checkoutReturn"
import {
  useCatalogue,
  useStartPackCheckout,
  useStartSubscriptionCheckout,
} from "@/lib/hooks/useBillingApi"
import { PHONE_CHECKOUT_BODY, PHONE_CHECKOUT_HEADING, isCheckoutPhoneRequired } from "@/lib/phone"
import { extraSeatsLine, planPreselect } from "@/lib/pricingModel"

/*
 * Plans and credit packs for one audience (spec §2.1, §2.2). Allowance sizes are hidden by
 * design, so a tier card sells on its `features` lines, its price and (teachers) its seats.
 * Prices come only from the catalogue: nothing here is a hard-coded number (PRODUCT.md: no
 * fabricated pricing).
 */

export interface PlansViewProps {
  audience: Audience
  beneficiaryId: string | null
  paths: BillingPaths
  currentTierId: string | null
  hasLiveSubscription: boolean
  canManage: boolean
  managedByName: string | null
  /** The interval the current subscription bills on; the toggle opens there. */
  currentInterval?: BillingInterval | null
}

const UNSAFE_URL = "Couldn't start checkout. Nothing was charged. Try again."

export function PlansView(props: PlansViewProps) {
  const { audience, beneficiaryId, paths, currentTierId, hasLiveSubscription, canManage, managedByName, currentInterval } = props
  const catalogue = useCatalogue(audience)
  const subCheckout = useStartSubscriptionCheckout()
  const packCheckout = useStartPackCheckout()
  // The public pricing page links here with `?plan=<code>&interval=`; an unknown code matches no tier.
  const [params] = useSearchParams()
  const preselect = planPreselect(params)
  // The visitor's own toggle wins; until then the preselected tier's interval (so `?plan=` alone
  // still opens on the right interval), then the URL's, then the held plan's.
  const [chosen, setChosen] = useState<BillingInterval | null>(null)
  const preselected = preselect.code ? catalogue.data?.tiers.find((t) => t.code === preselect.code) : undefined
  const interval: BillingInterval = chosen ?? preselected?.interval ?? preselect.interval ?? initialInterval(currentInterval)
  const [extraSeats, setExtraSeats] = useState(0)
  const [unsafe, setUnsafe] = useState(false)
  // After a successful start the payer is on their way to Paymob; keep the buttons off until the
  // page actually leaves, so a second click cannot create a second pending payment.
  const busy = subCheckout.isPending || packCheckout.isPending || subCheckout.isSuccess || packCheckout.isSuccess
  const resetSub = subCheckout.reset
  const resetPack = packCheckout.reset
  // Coming back with the browser's Back button can restore this page frozen mid-redirect.
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => {
      if (!e.persisted) return
      resetSub()
      resetPack()
    }
    window.addEventListener("pageshow", onShow)
    return () => window.removeEventListener("pageshow", onShow)
  }, [resetSub, resetPack])
  const buying = canManage
  // Which section the failed checkout came from, so its message sits beside the button that was
  // pressed. A pack bought at the bottom of a phone screen must not report its failure at the top.
  const [unsafeFrom, setUnsafeFrom] = useState<"plan" | "pack">("plan")
  const failureFor = (section: "plan" | "pack"): string | null => {
    if (unsafe) return unsafeFrom === section ? UNSAFE_URL : null
    const m = section === "plan" ? subCheckout : packCheckout
    return m.isError ? billingFailureMessage(m.error, "start checkout") : null
  }
  // UD-11: checkout refuses with 422 `phone_required` when the payer has no valid number on file.
  // That is not a failure to report, it is a missing step, so the section shows the field in place
  // and retries the same checkout the moment the number is saved. Nothing was charged: the server
  // checks before it writes a payment row.
  const retry = (section: "plan" | "pack") => {
    if (section === "plan") {
      if (subCheckout.variables) subCheckout.mutate(subCheckout.variables, { onSuccess: redirect("plan") })
    } else if (packCheckout.variables) {
      packCheckout.mutate(packCheckout.variables, { onSuccess: redirect("pack") })
    }
  }
  const phonePrompt = (section: "plan" | "pack") => {
    const m = section === "plan" ? subCheckout : packCheckout
    if (!m.isError || !isCheckoutPhoneRequired(m.error)) return null
    return (
      <div className="flex max-w-2xl flex-col gap-3 rounded-md border border-outline-variant bg-surface-container-low p-4">
        <div className="flex flex-col gap-1">
          <h3 className="m-0 text-display-xs text-on-surface">
            {PHONE_CHECKOUT_HEADING}
          </h3>
          <p className="m-0 text-body-sm text-on-surface-variant">{PHONE_CHECKOUT_BODY}</p>
        </div>
        <PhoneEntryForm autoFocus submitLabel="Save and continue" onSaved={() => retry(section)} />
      </div>
    )
  }
  const failureLine = (section: "plan" | "pack") => {
    const prompt = phonePrompt(section)
    if (prompt) return prompt
    const text = failureFor(section)
    return text ? (
      <p role="alert" className="m-0 text-body-sm text-error">
        {text}
      </p>
    ) : null
  }

  const redirect = (section: "plan" | "pack") => (res: { paymentId: string; checkoutUrl: string }) => {
    if (startCheckoutRedirect(res, paths.overview)) return
    setUnsafeFrom(section)
    setUnsafe(true)
    subCheckout.reset()
    packCheckout.reset()
  }

  const tierAction = (tier: PlanTier) => {
    if (!buying) return null
    if (tier.id === currentTierId) return <Button disabled>Current plan</Button>
    if (hasLiveSubscription) {
      return (
        <Link to={`${paths.overview}?change=${tier.id}`} className={buttonVariants({ variant: "secondary" })}>
          Change to {tier.name}
        </Link>
      )
    }
    return (
      <Button
        variant="primary"
        disabled={busy}
        loading={(subCheckout.isPending || subCheckout.isSuccess) && subCheckout.variables?.planTierId === tier.id}
        onClick={() => {
          setUnsafe(false)
          subCheckout.mutate(subscriptionCheckoutRequest(tier, audience, beneficiaryId, extraSeats), { onSuccess: redirect("plan") })
        }}
      >
        Choose {tier.name}
      </Button>
    )
  }

  const packAction = (pack: CreditPack) => {
    if (!buying) return null
    return (
      <Button
        variant="secondary"
        disabled={busy}
        loading={(packCheckout.isPending || packCheckout.isSuccess) && packCheckout.variables?.creditPackId === pack.id}
        onClick={() => {
          setUnsafe(false)
          packCheckout.mutate(packCheckoutRequest(pack, beneficiaryId), { onSuccess: redirect("pack") })
        }}
      >
        Buy {pack.name}
      </Button>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {!canManage ? (
        <p className="m-0 text-body-md text-on-surface-variant">
          {managedByName ?? "Someone else"} manages billing for this account. Ask them to make changes.
        </p>
      ) : null}
      <QueryState
        query={catalogue}
        skeleton={<CardGridSkeleton count={3} />}
        error={{ heading: "Couldn't load plans" }}
        isEmpty={(c) => c.tiers.length === 0 && c.packs.length === 0}
        empty={<EmptyState heading="No plans are on sale right now." body="Check back soon." />}
      >
        {(c) => {
          const tiers = tiersForInterval(c.tiers, interval)
          return (
            <>
              <section aria-labelledby="plans-heading" className="flex flex-col gap-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 id="plans-heading" className="m-0 text-display-sm text-on-surface">Plans</h2>
                  <ToggleGroup
                    type="single"
                    value={interval}
                    onValueChange={(v) => (v === "month" || v === "year" ? setChosen(v) : undefined)}
                    aria-label="Billing interval"
                  >
                    <ToggleGroupItem value="month">Monthly</ToggleGroupItem>
                    <ToggleGroupItem value="year">Yearly</ToggleGroupItem>
                  </ToggleGroup>
                </div>
                {audience === "teacher" && buying && !hasLiveSubscription ? (
                  <div className="max-w-xs">
                    <Input
                      label="Extra seats at checkout"
                      hint="Seats beyond the plan's included seats, billed with the plan."
                      name="extraSeats"
                      type="number"
                      inputMode="numeric"
                      min={0}
                      max={200}
                      value={extraSeats}
                      onChange={(e) => setExtraSeats(clampExtraSeats(Number(e.target.value)))}
                    />
                  </div>
                ) : null}
                <ul className="m-0 grid list-none gap-4 p-0 md:grid-cols-2 lg:grid-cols-3">
                  {tiers.map((tier) => (
                    <li key={tier.id}>
                      <Card className={tier.code === preselect.code ? "h-full border-primary" : "h-full"} data-preselected={tier.code === preselect.code ? "true" : undefined}>
                        <CardBody className="flex h-full flex-col gap-3">
                          <h3 className="m-0 text-display-sm text-on-surface">{tier.name}</h3>
                          {tier.code === preselect.code ? (
                            <p className="m-0 text-body-sm font-medium text-primary">Selected on the pricing page</p>
                          ) : null}
                          <p className="m-0">
                            <span className="text-data-lg text-on-surface">{formatMoney(tier.priceMinor, tier.currency)}</span>{" "}
                            <span className="text-body-sm text-on-surface-variant">{intervalLabel(tier.interval)}</span>
                          </p>
                          {tier.includedSeats !== null ? (
                            <p className="m-0 text-body-sm text-on-surface">{seatsIncludedLabel(tier.includedSeats)}</p>
                          ) : null}
                          {tier.extraSeatPriceMinor !== null ? (
                            <p className="m-0 text-body-sm text-on-surface-variant">
                              {extraSeatsLine(tier.extraSeatPriceMinor, tier.currency, tier.interval)}
                            </p>
                          ) : null}
                          <ul className="m-0 flex flex-1 list-none flex-col gap-2 p-0 text-body-sm text-on-surface">
                            {tier.features.map((f) => (
                              <li key={f} className="flex items-start gap-2">
                                <Check aria-hidden="true" weight="bold" className="mt-0.5 size-4 shrink-0 text-on-surface-variant" />
                                <span>{f}</span>
                              </li>
                            ))}
                          </ul>
                          {tierAction(tier)}
                        </CardBody>
                      </Card>
                    </li>
                  ))}
                </ul>
                {tiers.length === 0 ? (
                  <p className="m-0 text-body-sm text-on-surface-variant">
                    No {interval === "month" ? "monthly" : "yearly"} plans right now.
                  </p>
                ) : null}
                {failureLine("plan")}
              </section>
              <section id="packs" aria-labelledby="packs-heading" className="flex scroll-mt-24 flex-col gap-4">
                <h2 id="packs-heading" className="m-0 text-display-sm text-on-surface">Credit packs</h2>
                <p className="m-0 text-body-sm text-on-surface-variant">
                  Credits pay once a plan's allowance runs out, or on their own without a plan. They last 12 months from purchase.
                </p>
                <ul className="m-0 grid list-none gap-4 p-0 md:grid-cols-2 lg:grid-cols-3">
                  {c.packs.map((pack) => (
                    <li key={pack.id}>
                      <Card className="h-full">
                        <CardBody className="flex h-full flex-col gap-2">
                          <h3 className="m-0 text-display-xs text-on-surface">{pack.name}</h3>
                          {pack.name.includes(formatCredits(pack.units)) ? null : (
                            <p className="m-0 text-data-sm text-on-surface-variant">{formatCredits(pack.units)}</p>
                          )}
                          <p className="m-0 flex-1 text-data-md text-on-surface">{formatMoney(pack.priceMinor, pack.currency)}</p>
                          {packAction(pack)}
                        </CardBody>
                      </Card>
                    </li>
                  ))}
                </ul>
                {failureLine("pack")}
              </section>
            </>
          )
        }}
      </QueryState>
    </div>
  )
}

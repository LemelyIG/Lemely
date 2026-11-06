/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* V3: this is a Persuade page built from the app's own tier-card and toggle primitives, so it shares the signed-in plans page's rhythm on purpose (a visitor who signs in lands on the same shapes); credit packs are rows rather than a second card grid so the page does not repeat one template twice. */
import { useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Check } from "@phosphor-icons/react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { CardGridSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useAuth } from "@/lib/auth/AuthContext"
import { formatCredits, formatMoney, intervalLabel } from "@/lib/billingFormat"
import type { Audience, BillingInterval } from "@/lib/billingTypes"
import { usePublicCatalogue } from "@/lib/hooks/useBillingApi"
import {
  chooseTarget,
  extraSeatsLine,
  packsTarget,
  planPath,
  publicCatalogueBody,
  rateLimitSeconds,
  rateLimitSentence,
  signupHref,
  tiersForInterval,
} from "@/lib/pricingModel"
import { MarketingFrame } from "@/portals/marketing"

/*
 * `/pricing`: public prices from `GET /billing/public-catalogue` (plan 02, no auth). Nothing here
 * is a hard-coded number (PRODUCT.md: no fabricated pricing). Choosing a plan goes to the
 * signed-in plans page, which preselects the tier by its code, because the public catalogue
 * carries no ids and this page never starts a checkout. A signed-out visitor goes through
 * sign-in or sign-up first (both carry `next`); a signed-in one goes straight there, because
 * `/login` drops `next` for an existing session.
 *
 * Persuade mode, but the page's job is to be believed: prices, seats and one clear way forward.
 * No eyebrows, no "most popular" badge (nothing in the catalogue says which tier is), and no
 * allowance sizes (the backend hides them by design).
 */

const TEXT_LINK =
  "font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center"

/** Whole seconds left until `seconds` from mount have passed; restarts when `resetKey` changes. */
function useCountdown(seconds: number, resetKey: unknown): number {
  const [clock, setClock] = useState(() => {
    const t = Date.now()
    return { end: t + seconds * 1000, now: t }
  })
  useEffect(() => {
    const start = Date.now()
    const end = start + seconds * 1000
    setClock({ end, now: start })
    const id = window.setInterval(() => {
      const now = Date.now()
      setClock({ end, now })
      if (now >= end) window.clearInterval(id)
    }, 250)
    return () => window.clearInterval(id)
  }, [seconds, resetKey])
  return Math.max(0, Math.ceil((clock.end - clock.now) / 1000))
}

/**
 * A 429 with a usable `Retry-After`. Screen readers hear it in two coarse steps, never per tick:
 * the alert states the reason and the initial wait once, and a visually hidden status speaks again
 * only when Try again unlocks. The visible countdown is a `timer` (silent by default), and Try
 * again stays locked until it reaches zero so a visitor cannot hammer a route that said wait.
 */
function RateLimited({ seconds, error, onRetry, retrying }: { seconds: number; error: unknown; onRetry: () => void; retrying: boolean }) {
  const left = useCountdown(seconds, error)
  return (
    <div className="flex max-w-lg flex-col gap-3 rounded-lg border border-outline-variant bg-surface-container-low p-5">
      <p role="alert" className="sr-only">
        Couldn&apos;t load prices. {rateLimitSentence(seconds)}
      </p>
      <p role="status" className="sr-only">
        {left === 0 ? rateLimitSentence(0) : ""}
      </p>
      <p aria-hidden="true" className="m-0 text-body-lg font-medium text-on-surface">
        Couldn&apos;t load prices
      </p>
      <p role="timer" className="m-0 text-body-md text-on-surface-variant">
        {rateLimitSentence(left)}
      </p>
      <div>
        <Button variant="secondary" disabled={left > 0 || retrying} loading={retrying} onClick={onRetry}>
          Try again
        </Button>
      </div>
    </div>
  )
}

export function Pricing() {
  const [params] = useSearchParams()
  const [audience, setAudience] = useState<Audience>(params.get("audience") === "teacher" ? "teacher" : "student")
  const [interval, setInterval] = useState<BillingInterval>("month")
  const catalogue = usePublicCatalogue(audience)
  const signedIn = useAuth().session !== null
  const wait = catalogue.status === "error" ? rateLimitSeconds(catalogue.error) : null

  return (
    <MarketingFrame>
      <div className="mx-auto flex w-full max-w-app flex-col gap-8 px-page-mobile py-12 md:px-page-desktop md:py-16">
        <h1 className="m-0 text-display-xl text-on-surface">Pricing</h1>
        <div className="flex flex-wrap gap-3">
          <ToggleGroup type="single" value={audience} onValueChange={(v) => (v === "student" || v === "teacher" ? setAudience(v) : undefined)} aria-label="Who is this for">
            <ToggleGroupItem value="student">Students</ToggleGroupItem>
            <ToggleGroupItem value="teacher">Teachers</ToggleGroupItem>
          </ToggleGroup>
          <ToggleGroup type="single" value={interval} onValueChange={(v) => (v === "month" || v === "year" ? setInterval(v) : undefined)} aria-label="Billing interval">
            <ToggleGroupItem value="month">Monthly</ToggleGroupItem>
            <ToggleGroupItem value="year">Yearly</ToggleGroupItem>
          </ToggleGroup>
        </div>
        {wait !== null ? (
          <RateLimited seconds={wait} error={catalogue.error} onRetry={() => void catalogue.refetch()} retrying={catalogue.isFetching} />
        ) : (
          <QueryState
            query={catalogue}
            skeleton={<CardGridSkeleton count={3} />}
            error={{ heading: "Couldn't load prices", body: publicCatalogueBody, kicker: null }}
            isEmpty={(c) => c.tiers.length === 0 && c.packs.length === 0}
            empty={<EmptyState heading="No plans are on sale right now." body="Check back soon." kicker={null} />}
          >
            {(c) => {
              const tiers = tiersForInterval(c.tiers, interval)
              return (
                <>
                  <section aria-labelledby="pricing-plans" className="flex flex-col gap-4">
                    <h2 id="pricing-plans" className="pricing-section-title text-on-surface">Plans</h2>
                    <ul className="m-0 grid list-none gap-4 p-0 md:grid-cols-2 lg:grid-cols-3">
                      {tiers.map((tier) => (
                        <li key={tier.code}>
                          <Card className="h-full">
                            <CardBody className="flex h-full flex-col gap-3">
                              <h3 className="m-0 text-display-sm text-on-surface">{tier.name}</h3>
                              <p className="m-0">
                                <span className="text-data-lg text-on-surface">{formatMoney(tier.priceMinor, tier.currency)}</span>{" "}
                                <span className="text-body-sm text-on-surface-variant">{intervalLabel(tier.interval)}</span>
                              </p>
                              {tier.includedSeats !== null ? <p className="m-0 text-body-sm text-on-surface">{tier.includedSeats} student seats included</p> : null}
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
                              <Link to={chooseTarget(tier, signedIn)} className={buttonVariants({ variant: "primary" })}>Choose {tier.name}</Link>
                              {signedIn ? null : (
                                <Link to={signupHref(audience, planPath(tier))} className={TEXT_LINK}>
                                  New to Lemely? Sign up<span className="sr-only"> for {tier.name}</span>
                                </Link>
                              )}
                            </CardBody>
                          </Card>
                        </li>
                      ))}
                    </ul>
                    {tiers.length === 0 ? (
                      <p className="m-0 text-body-sm text-on-surface-variant">No {interval === "month" ? "monthly" : "yearly"} plans right now.</p>
                    ) : null}
                    {signedIn ? null : (
                      <p className="m-0 text-body-sm text-on-surface-variant">
                        New to Lemely?{" "}
                        <Link to={signupHref(audience)} className={TEXT_LINK}>Create a {audience} account</Link>
                      </p>
                    )}
                  </section>
                  <section id="packs" aria-labelledby="pricing-packs" className="flex scroll-mt-24 flex-col gap-4">
                    <h2 id="pricing-packs" className="pricing-section-title text-on-surface">Credit packs</h2>
                    <p className="m-0 text-body-sm text-on-surface-variant">Credits last 12 months from purchase.</p>
                    {c.packs.length === 0 ? (
                      <p className="m-0 text-body-sm text-on-surface-variant">No credit packs right now.</p>
                    ) : (
                      <ul className="m-0 flex max-w-3xl list-none flex-col divide-y divide-outline-variant rounded-lg border border-outline-variant bg-surface-container-lowest p-0">
                        {c.packs.map((pack) => (
                          <li key={pack.code} className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
                            <div className="flex min-w-0 flex-col">
                              <h3 className="m-0 text-body-lg font-medium text-on-surface">{pack.name}</h3>
                              {pack.name.includes(formatCredits(pack.units)) ? null : (
                                <p className="m-0 text-data-sm text-on-surface-variant">{formatCredits(pack.units)}</p>
                              )}
                            </div>
                            <div className="flex items-center gap-4">
                              <p className="m-0 text-data-md text-on-surface">{formatMoney(pack.priceMinor, pack.currency)}</p>
                              <Link to={packsTarget(audience, signedIn)} className={TEXT_LINK}>
                                {signedIn ? "Choose pack" : "Sign in to buy"}<span className="sr-only"> {pack.name}</span>
                              </Link>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </>
              )
            }}
          </QueryState>
        )}
      </div>
    </MarketingFrame>
  )
}

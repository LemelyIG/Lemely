/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import {
  CREDIT_RATE_FIELDS,
  creditRateClearBody,
  creditRateSetBody,
  creditRateUnchanged,
  creditRateValues,
  staleBlock,
  unitsPerMajor,
  unitsPerMinorText,
} from "@/lib/adminRatesModel"
import { useClearCreditRate, useCreditRates, useSetCreditRate } from "@/lib/hooks/useAdminBillingApi"
import type { CreditRate } from "@/lib/billingTypes"
import { ChangedBy, Empty, Section } from "./CataloguePanels"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/* Credit conversion (UD-12): how many units a payment that cannot buy its plan turns into. With
 * no rate, such a payment stays paid and raises an alert, so Clear says so before it stops them. */

/** The one currency Paymob Egypt settles; the panel still lists whatever rows the server holds. */
const DEFAULT_CURRENCY = "EGP"

type Dialog = { kind: "set"; currency: string; rate: CreditRate | null } | { kind: "clear"; rate: CreditRate } | null

export function CreditConversion({ saved }: { saved: (what: string) => () => void }) {
  const query = useCreditRates()
  const setRate = useSetCreditRate()
  const clearRate = useClearCreditRate()
  const [dialog, setDialog] = useState<Dialog>(null)
  const close = () => setDialog(null)
  const empty = query.data?.length === 0

  return (
    <Section
      title="Credit conversion"
      hint="Units a customer gets for a payment that turns into credits. Applies to payments after you save."
      action={
        empty ? (
          <Button variant="secondary" onClick={() => setDialog({ kind: "set", currency: DEFAULT_CURRENCY, rate: null })}>
            Set rate
          </Button>
        ) : null
      }
    >
      <QueryState
        query={query}
        skeleton={<ListSkeleton rows={1} />}
        error={{ heading: "Couldn't load the conversion rates", compact: true }}
        isEmpty={(rates) => rates.length === 0}
        empty={<Empty>No rate set. Payments that would become credits stay paid and raise an alert.</Empty>}
      >
        {(rates) => (
          <ul className="m-0 flex list-none flex-col p-0">
            {rates.map((r) => (
              <li key={r.currency} className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-outline-variant py-3 first:border-t-0">
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-data-md">
                    1 {r.currency} = {unitsPerMajor(r.unitsPerMinor)} units
                  </span>
                  <span className="text-body-sm text-on-surface-variant">
                    <span className="text-data-sm">{unitsPerMinorText(r.unitsPerMinor)}</span> units per piaster
                  </span>
                  <ChangedBy at={r.updatedAt} by={r.updatedBy} />
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "set", currency: r.currency, rate: r })} aria-label={`Set ${r.currency} rate`}>
                    Set
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setDialog({ kind: "clear", rate: r })} aria-label={`Clear ${r.currency} rate`}>
                    Clear
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
      {dialog?.kind === "set" ? (
        <ReasonedFormDialog
          key={dialog.rate?.version ?? "new"}
          open
          onClose={close}
          title={`Set ${dialog.currency} rate`}
          fields={CREDIT_RATE_FIELDS}
          initial={creditRateValues(dialog.rate)}
          submitLabel="Save rate"
          mutation={setRate}
          toBody={(v, r) => ({ currency: dialog.currency, body: creditRateSetBody(v, r, dialog.rate) })}
          check={(v) => creditRateUnchanged(v, dialog.rate)}
          blocked={staleBlock(setRate.error)}
          reload="Reload this page"
          onSaved={saved(`Saved the ${dialog.currency} rate.`)}
        />
      ) : null}
      {dialog?.kind === "clear" ? (
        <ReasonedFormDialog
          open
          onClose={close}
          title={`Clear ${dialog.rate.currency} rate`}
          fields={[]}
          initial={{}}
          submitLabel="Stop conversions"
          mutation={clearRate}
          toBody={(_v, r) => ({ currency: dialog.rate.currency, body: creditRateClearBody(r, dialog.rate) })}
          note={<p className="m-0 text-body-sm text-on-surface">Payments that would become credits will stay paid and alert you instead.</p>}
          blocked={staleBlock(clearRate.error)}
          reload="Reload this page"
          onSaved={saved(`Cleared the ${dialog.rate.currency} rate.`)}
        />
      ) : null}
    </Section>
  )
}

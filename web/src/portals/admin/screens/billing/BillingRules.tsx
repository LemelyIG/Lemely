import { useState } from "react"
import { Button } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { SETTINGS_FIELDS, settingsBody, settingsNothingChanged, settingsValues, staleBlock, trimDecimal } from "@/lib/adminRatesModel"
import { useBillingSettings, useUpdateBillingSettings } from "@/lib/hooks/useAdminBillingApi"
import type { BillingSettings } from "@/lib/billingTypes"
import { ChangedBy, Section } from "./CataloguePanels"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/* Billing rules (UD-13): the few numbers that steer billing and were once constants. Values are
 * read-only until Edit; a save sends only what changed, with the version that was read. */

const n = (v: number) => new Intl.NumberFormat("en-US").format(v)
const plural = (v: number, word: string) => `${n(v)} ${word}${v === 1 ? "" : "s"}`

function Rule({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-on-surface-variant">{label}</dt>
      <dd className="m-0 text-data-md">{children}</dd>
    </div>
  )
}

function Values({ s }: { s: BillingSettings }) {
  return (
    <div className="flex flex-col gap-3">
      <dl className="m-0 grid gap-x-8 gap-y-4 text-body-sm sm:grid-cols-2 xl:grid-cols-3">
        <Rule label="Credit validity">{plural(s.creditValidityMonths, "month")}</Rule>
        <Rule label="Grace period">{plural(s.graceDays, "day")}</Rule>
        <Rule label="Price-change notice">{plural(s.priceChangeNoticeDays, "day")}</Rule>
        <Rule label="Extra-seat ceiling">{plural(s.maxExtraSeats, "seat")}</Rule>
        <Rule label="Margin rate">{s.marginEgpPerUsd === null ? "Not set" : `${trimDecimal(s.marginEgpPerUsd)} EGP per USD`}</Rule>
        <Rule label="Code execution">
          {s.codeExecutionUsdPerHour === null ? "Built-in rate" : `$${trimDecimal(s.codeExecutionUsdPerHour)} per container hour`}
        </Rule>
      </dl>
      <ChangedBy at={s.updatedAt} by={s.updatedBy} />
    </div>
  )
}

export function BillingRules({ saved }: { saved: (what: string) => () => void }) {
  const query = useBillingSettings()
  const update = useUpdateBillingSettings()
  const [editing, setEditing] = useState(false)
  const current = query.data

  return (
    <Section
      title="Billing rules"
      hint="Apply from the moment you save. Credits and payments already made keep the terms they had."
      action={
        current ? (
          <Button variant="secondary" onClick={() => setEditing(true)} aria-label="Edit billing rules">
            Edit
          </Button>
        ) : null
      }
    >
      <QueryState query={query} skeleton={<ListSkeleton rows={2} />} error={{ heading: "Couldn't load the billing rules" }}>
        {(s) => (
          <>
            <Values s={s} />
            {editing ? (
              <ReasonedFormDialog
                open
                onClose={() => setEditing(false)}
                title="Billing rules"
                fields={SETTINGS_FIELDS}
                initial={settingsValues(s)}
                submitLabel="Save rules"
                mutation={update}
                toBody={(v, r) => settingsBody(v, r, s)}
                check={(v) => settingsNothingChanged(v, s)}
                blocked={staleBlock(update.error)}
                reload="Reload this page"
                onSaved={saved("Saved the billing rules.")}
              />
            ) : null}
          </>
        )}
      </QueryState>
    </Section>
  )
}

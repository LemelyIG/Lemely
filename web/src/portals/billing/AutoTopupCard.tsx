import { useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { formFromSettings, toUpdate, validateAutoTopup, type AutoTopupFormState } from "@/lib/autoTopupForm"
import { formatCredits, formatMoney } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { Audience, AutoTopupSettings, CreditPack, SavedCardView } from "@/lib/billingTypes"
import { useAutoTopup, useBillingSummary, useCatalogue, useSaveAutoTopup, useSavedCards } from "@/lib/hooks/useBillingApi"

/*
 * Auto top-up (spec §2.1, §5.5). Payer-only. The server enforces the threshold, the cap and
 * the one-charge-in-flight rule; this form only collects the settings.
 */

function Form({
  settings,
  packs,
  cards,
  beneficiaryId,
  packsHref,
}: {
  settings: AutoTopupSettings
  packs: CreditPack[]
  cards: SavedCardView[]
  beneficiaryId: string | null
  packsHref: string
}) {
  const save = useSaveAutoTopup()
  const [form, setForm] = useState<AutoTopupFormState>(() => formFromSettings(settings))
  const [submitted, setSubmitted] = useState(false)
  const errors = validateAutoTopup(form, packs)
  const set = (patch: Partial<AutoTopupFormState>) => setForm((f) => ({ ...f, ...patch }))
  const noCard = cards.length === 0

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        setSubmitted(true)
        if (errors.length === 0) save.mutate(toUpdate(form, beneficiaryId))
      }}
    >
      {settings.disabledReason === "charge_failed" ? (
        <p role="status" className="m-0 rounded-lg bg-surface-container-high p-3 text-body-sm text-on-surface">
          Auto top-up was switched off because the last charge failed. Check the card, then switch it back on.
        </p>
      ) : null}
      <Switch
        label="Top up automatically"
        description="Buy a pack by card when your credits run low."
        layout="row"
        checked={form.enabled}
        disabled={noCard}
        onCheckedChange={(enabled) => set({ enabled })}
      />
      {noCard ? (
        <p className="m-0 text-body-sm text-on-surface-variant">
          Auto top-up needs a saved card. Buy a credit pack by card once and Lemely keeps the card.{" "}
          <Link to={packsHref} className="font-medium text-primary underline-offset-2 hover:underline">
            Buy credits
          </Link>
        </p>
      ) : null}
      <div className="grid gap-4 md:grid-cols-2">
        <Input
          label="When credits fall below"
          type="number"
          inputMode="numeric"
          min={1}
          value={form.thresholdUnits}
          onChange={(e) => set({ thresholdUnits: e.target.value })}
        />
        <Select label="Buy this pack" value={form.creditPackId ?? ""} onChange={(e) => set({ creditPackId: e.target.value || null })}>
          <option value="">Choose a pack</option>
          {packs.map((p) => (
            <option key={p.id} value={p.id}>
              {formatCredits(p.units)} for {formatMoney(p.priceMinor, p.currency)}
            </option>
          ))}
        </Select>
        <Select label="Charge this card" value={form.savedCardId ?? ""} onChange={(e) => set({ savedCardId: e.target.value || null })} disabled={noCard}>
          <option value="">Choose a card</option>
          {cards.map((c) => (
            <option key={c.cardId} value={c.cardId}>
              {c.brand} {c.maskedPan}
            </option>
          ))}
        </Select>
        <Input
          label={`Spend at most per month (${settings.currency})`}
          hint={`Spent this month: ${formatMoney(settings.spentThisMonthMinor, settings.currency)}`}
          type="number"
          inputMode="decimal"
          min={0}
          step="0.01"
          value={form.monthlyCapMajor}
          onChange={(e) => set({ monthlyCapMajor: e.target.value })}
        />
      </div>
      {submitted && errors.length > 0 ? (
        <div role="alert" className="flex flex-col gap-1 text-body-sm text-error">
          {errors.map((m) => (
            <p key={m} className="m-0">
              {m}
            </p>
          ))}
        </div>
      ) : null}
      {save.isError ? (
        <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(save.error, "save auto top-up")}</p>
      ) : null}
      {save.isSuccess ? (
        <p role="status" className="m-0 text-body-sm text-on-surface-variant">Saved.</p>
      ) : null}
      <Button type="submit" variant="primary" loading={save.isPending} className="min-h-11 self-start">
        Save auto top-up
      </Button>
    </form>
  )
}

export function AutoTopupCard({
  beneficiaryId,
  audience,
  packsHref,
}: {
  beneficiaryId: string | null
  audience: Audience
  packsHref: string
}) {
  const summary = useBillingSummary(beneficiaryId)
  const settings = useAutoTopup(beneficiaryId)
  const cards = useSavedCards()
  const catalogue = useCatalogue(audience)
  if (!summary.data?.canManage) return null
  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        <h2 className="m-0 text-display-sm text-on-surface">Auto top-up</h2>
        {settings.isError || cards.isError || catalogue.isError ? (
          <p role="alert" className="m-0 text-body-sm text-error">Couldn't load auto top-up settings. Reload the page to try again.</p>
        ) : settings.data && cards.data && catalogue.data ? (
          <Form
            key={JSON.stringify(settings.data)}
            settings={settings.data}
            packs={catalogue.data.packs}
            cards={cards.data.cards}
            beneficiaryId={beneficiaryId}
            packsHref={packsHref}
          />
        ) : (
          <p role="status" className="m-0 text-body-sm text-on-surface-variant">Loading auto top-up…</p>
        )}
      </CardBody>
    </Card>
  )
}

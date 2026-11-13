/* Hallmark · pre-emit critique: P4 H3 E3 S4 R4 V3 */
/* Impeccable retro audit: the pending line is a skeleton and the failure is the compact C-11 ErrorState with a retry. H3: the form is one even grid of four fields under a switch. */
import { useEffect, useReducer, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { SkeletonText } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/ui/state-views"
import { Switch } from "@/components/ui/switch"
import {
  autoTopupReducer,
  disabledNotice,
  fieldErrors,
  formFromSettings,
  initialState,
  showSaved,
  switchDisabled,
  toUpdate,
  validateAutoTopup,
  type AutoTopupFormState,
} from "@/lib/autoTopupForm"
import { formatCredits, formatMoney } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { Audience, AutoTopupSettings, CreditPack, SavedCardView } from "@/lib/billingTypes"
import { useAutoTopup, useBillingSummary, useCatalogue, useSaveAutoTopup, useSavedCards } from "@/lib/hooks/useBillingApi"

/*
 * Auto top-up (spec §2.1, §5.5). Payer-only. The server enforces the threshold, the cap and
 * the one-charge-in-flight rule; this form only collects the settings.
 */

const LINK = "font-medium text-primary underline-offset-2 hover:underline"
const PACK_GONE = "Your saved pack is no longer available. Choose another."

/** Server values as form fields. A saved pack the catalogue no longer lists is cleared so the
 * user has to choose again. */
function serverForm(settings: AutoTopupSettings, packs: CreditPack[]): AutoTopupFormState {
  const form = formFromSettings(settings)
  return packs.some((p) => p.id === form.creditPackId) ? form : { ...form, creditPackId: null }
}

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
  const server = serverForm(settings, packs)
  const [state, dispatch] = useReducer(autoTopupReducer, server, initialState)
  const [seen, setSeen] = useState(settings)
  // The form stays mounted across refetches; the reducer decides whether new server values win.
  if (seen !== settings) {
    setSeen(settings)
    dispatch({ type: "serverSettings", server })
  }
  const { form } = state
  const [announce, setAnnounce] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [focusTick, setFocusTick] = useState(0)
  const formRef = useRef<HTMLFormElement>(null)
  const errors = fieldErrors(form, packs)
  const messages = validateAutoTopup(form, packs)
  const set = (patch: Partial<AutoTopupFormState>) => {
    setAnnounce(false)
    dispatch({ type: "edit", patch })
  }
  const noCard = cards.length === 0
  const packGone = settings.creditPackId !== null && server.creditPackId === null
  const shown = (f: keyof typeof errors) => (submitted ? errors[f] : undefined)
  const notice = disabledNotice(settings.disabledReason)

  useEffect(() => {
    if (focusTick > 0) formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
  }, [focusTick])

  return (
    <form
      ref={formRef}
      noValidate
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        setSubmitted(true)
        if (messages.length > 0) {
          setAnnounce(true)
          setFocusTick((n) => n + 1)
          return
        }
        save.mutate(toUpdate(form, beneficiaryId, settings.monthlyCapMinor), {
          onSuccess: (saved) => {
            dispatch({ type: "saveSucceeded", saved: serverForm(saved, packs) })
            setSubmitted(false)
          },
          onError: () => dispatch({ type: "saveFailed" }),
        })
      }}
    >
      {notice ? (
        <p role="status" className="m-0 rounded-lg bg-surface-container-high p-3 text-body-sm text-on-surface">
          {notice === "charge_failed" ? (
            <>
              Auto top-up was switched off because the last charge failed. Check the card, then switch it back on. To use a new card,{" "}
              <Link to={packsHref} className={LINK}>
                buy a pack with it
              </Link>
              .
            </>
          ) : (
            "Auto top-up was switched off. Check the settings below, then switch it back on."
          )}
        </p>
      ) : null}
      <Switch
        label="Top up automatically"
        description="Buy a pack by card when your credits run low."
        layout="row"
        checked={form.enabled}
        disabled={switchDisabled(form, !noCard)}
        onCheckedChange={(enabled) => set({ enabled })}
      />
      {noCard ? (
        <p className="m-0 text-body-sm text-on-surface-variant">
          Auto top-up needs a saved card. Buy a credit pack by card once and Lemely keeps the card.{" "}
          <Link to={packsHref} className={LINK}>
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
          error={shown("thresholdUnits")}
          onChange={(e) => set({ thresholdUnits: e.target.value })}
        />
        <Select
          label="Buy this pack"
          value={form.creditPackId ?? ""}
          hint={packGone && form.creditPackId === null ? PACK_GONE : undefined}
          error={shown("creditPackId")}
          onChange={(e) => set({ creditPackId: e.target.value || null })}
        >
          <option value="">Choose a pack</option>
          {packs.map((p) => (
            <option key={p.id} value={p.id}>
              {formatCredits(p.units)} for {formatMoney(p.priceMinor, p.currency)}
            </option>
          ))}
        </Select>
        <Select
          label="Charge this card"
          value={form.savedCardId ?? ""}
          error={shown("savedCardId")}
          onChange={(e) => set({ savedCardId: e.target.value || null })}
          disabled={noCard}
        >
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
          error={shown("monthlyCapMajor")}
          onChange={(e) => set({ monthlyCapMajor: e.target.value })}
        />
      </div>
      {submitted && messages.length > 0 ? (
        <div role={announce ? "alert" : undefined} className="flex flex-col gap-1 text-body-sm text-error">
          {messages.map((m) => (
            <p key={m} className="m-0">
              {m}
            </p>
          ))}
        </div>
      ) : null}
      {save.isError ? (
        <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(save.error, "save auto top-up")}</p>
      ) : null}
      {showSaved(state) ? (
        <p role="status" className="m-0 text-body-sm text-on-surface-variant">Saved.</p>
      ) : null}
      <Button type="submit" variant="primary" loading={save.isPending} className="min-h-11 self-start">
        Save auto top-up
      </Button>
    </form>
  )
}

/** The queries below run only for a payer, so a non-payer never makes a request that 404s. */
function PayerCard({ beneficiaryId, audience, packsHref }: { beneficiaryId: string | null; audience: Audience; packsHref: string }) {
  const settings = useAutoTopup(beneficiaryId)
  const cards = useSavedCards()
  const catalogue = useCatalogue(audience)
  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        <h2 className="m-0 text-display-sm text-on-surface">Auto top-up</h2>
        {settings.isError || cards.isError || catalogue.isError ? (
          // The C-11 compact failure (neutral tone, polite), with a retry for whichever read failed.
          <ErrorState
            compact
            heading="Couldn't load your auto top-up settings"
            body="Nothing has changed on your account."
            action={{
              label: "Try again",
              onClick: () => {
                if (settings.isError) void settings.refetch()
                if (cards.isError) void cards.refetch()
                if (catalogue.isError) void catalogue.refetch()
              },
            }}
          />
        ) : settings.data && cards.data && catalogue.data ? (
          <Form
            key={beneficiaryId ?? "self"}
            settings={settings.data}
            packs={catalogue.data.packs}
            cards={cards.data.cards}
            beneficiaryId={beneficiaryId}
            packsHref={packsHref}
          />
        ) : (
          <SkeletonText lines={3} />
        )}
      </CardBody>
    </Card>
  )
}

export function AutoTopupCard(props: { beneficiaryId: string | null; audience: Audience; packsHref: string }) {
  const summary = useBillingSummary(props.beneficiaryId)
  if (!summary.data?.canManage) return null
  return <PayerCard {...props} />
}

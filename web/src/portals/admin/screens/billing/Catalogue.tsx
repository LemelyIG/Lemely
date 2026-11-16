/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useState } from "react"
import { WarningCircle } from "@phosphor-icons/react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { ErrorState } from "@/components/ui/state-views"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import {
  ESTIMATOR_FIELDS,
  FREE_FIELDS,
  PACK_FIELDS,
  PACK_UPDATE_FIELDS,
  RATE_FIELDS,
  TIER_FIELDS,
  TIER_UPDATE_FIELDS,
  estimatorBody,
  estimatorErrors,
  freeChanges,
  formatUtc,
  hiddenFeatureCount,
  freeValues,
  isForbidden,
  packBody,
  packUpdateBody,
  packValues,
  paymobState,
  rateBody,
  tierBody,
  tierUpdateBody,
  tierValues,
  versionRows,
  type VersionStatus,
} from "@/lib/adminBillingModel"
import { staleBlock } from "@/lib/adminRatesModel"
import { formatMoney } from "@/lib/billingFormat"
import type { AdminCatalogue, AdminCreditPack, AdminPlanTier, FreeAllowances } from "@/lib/billingTypes"
import {
  useAdminCatalogue,
  useCreateEstimator,
  useCreatePack,
  useCreateRate,
  useCreateTier,
  useSyncTier,
  useUpdateFreeAllowances,
  useUpdatePack,
  useUpdateTier,
} from "@/lib/hooks/useAdminBillingApi"
import { BillingRules } from "./BillingRules"
import { Empty, Section } from "./CataloguePanels"
import { CreditConversion } from "./CreditConversion"
import { LlmPrices } from "./LlmPrices"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/* Catalogue (spec §8.1): every price, allowance, pack, rate and estimator is data, versioned
 * where it affects charging, and every change carries a reason. */

type Dialog =
  | { kind: "tier"; tier: AdminPlanTier | null }
  | { kind: "sync"; tier: AdminPlanTier }
  | { kind: "pack"; pack: AdminCreditPack | null }
  | { kind: "rate" }
  | { kind: "estimator" }
  | { kind: "free"; free: FreeAllowances }
  | null

const n = (v: number) => new Intl.NumberFormat().format(v)
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const intervalWord = (t: AdminPlanTier) => (t.interval === "year" ? "yearly" : t.interval === "month" ? "monthly" : "no interval")

function OnSale({ on }: { on: boolean }) {
  return on ? (
    <Badge tone="ok" className="whitespace-nowrap">
      On sale
    </Badge>
  ) : (
    <span className="whitespace-nowrap text-body-sm text-on-surface-variant">Off sale</span>
  )
}

/** The Paymob column: the plan id, then what the drift check found. */
function PaymobCell({ tier }: { tier: AdminPlanTier }) {
  const state = paymobState(tier)
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-data-sm">{tier.paymobPlanId ?? "No plan"}</span>
      {state.tone === "attention" ? (
        <span role="note" className="inline-flex items-start gap-1 text-body-sm text-error">
          <WarningCircle size={16} weight="fill" aria-hidden className="mt-0.5 shrink-0" />
          {state.text}
        </span>
      ) : (
        <span className="text-body-sm text-on-surface-variant">{state.text}</span>
      )}
    </div>
  )
}

function TierSeats({ tier }: { tier: AdminPlanTier }) {
  if (tier.includedSeats === null) return <span className="text-on-surface-variant">No seats</span>
  return (
    <div className="flex flex-col whitespace-nowrap text-body-sm">
      <span className="text-data-sm">{n(tier.includedSeats)} seats</span>
      <span className="text-on-surface-variant">
        <span className="text-data-sm">{n(tier.seatAllowanceUnits ?? 0)}</span> units each
      </span>
      <span className="text-on-surface-variant">
        Extra <span className="text-data-sm">{formatMoney(tier.extraSeatPriceMinor ?? 0, tier.currency)}</span>
      </span>
    </div>
  )
}

function TierActions({ tier, open }: { tier: AdminPlanTier; open: (d: Dialog) => void }) {
  const state = paymobState(tier)
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="secondary" onClick={() => open({ kind: "tier", tier })} aria-label={`Edit ${tier.code}`}>
        Edit
      </Button>
      {state.canSync ? (
        <Button
          size="sm"
          variant={state.tone === "attention" ? "primary" : "ghost"}
          onClick={() => open({ kind: "sync", tier })}
          aria-label={`Sync ${tier.code} to Paymob`}
        >
          Sync to Paymob
        </Button>
      ) : null}
    </div>
  )
}

/** Wide screens read tiers as a table; narrower ones as one card per tier (ten columns do not fit). */
function Tiers({ tiers, open }: { tiers: AdminPlanTier[]; open: (d: Dialog) => void }) {
  if (tiers.length === 0) return <Empty>No plan tiers yet. Create the first one.</Empty>
  return (
    <>
      <div className="hidden xl:block">
        <Table density="operate">
          <caption className="sr-only">Plan tiers</caption>
          <THead>
            <TR>
              <TH>Plan</TH>
              <TH numeric>Price</TH>
              <TH numeric>Allowance</TH>
              <TH>Seats</TH>
              <TH>Sale</TH>
              <TH>Paymob</TH>
              <TH>
                <span className="sr-only">Actions</span>
              </TH>
            </TR>
          </THead>
          <TBody>
            {tiers.map((t) => (
              <TR key={t.id}>
                <TD>
                  <div className="flex flex-col">
                    <span>{t.name}</span>
                    <span className="text-data-sm text-on-surface-variant">{t.code}</span>
                    <span className="text-body-sm text-on-surface-variant">
                      {cap(t.audience)}, {intervalWord(t)}
                    </span>
                  </div>
                </TD>
                <TD numeric>{formatMoney(t.priceMinor, t.currency)}</TD>
                <TD numeric>{n(t.allowanceUnits)}</TD>
                <TD>
                  <TierSeats tier={t} />
                </TD>
                <TD>
                  <OnSale on={t.isActive} />
                </TD>
                <TD>
                  <PaymobCell tier={t} />
                </TD>
                <TD>
                  <TierActions tier={t} open={open} />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
      <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 md:grid-cols-2 xl:hidden">
        {tiers.map((t) => (
          <li key={t.id} className="flex flex-col gap-3 rounded-lg border border-outline-variant bg-surface-container-lowest p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 flex-col">
                <h3 className="m-0 text-body-lg font-medium text-on-surface">{t.name}</h3>
                <span className="text-data-sm text-on-surface-variant">{t.code}</span>
              </div>
              <OnSale on={t.isActive} />
            </div>
            <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-3 text-body-sm">
              <div>
                <dt className="text-on-surface-variant">Audience</dt>
                <dd className="m-0">
                  {cap(t.audience)}, {intervalWord(t)}
                </dd>
              </div>
              <div>
                <dt className="text-on-surface-variant">Price</dt>
                <dd className="m-0 text-data-md">{formatMoney(t.priceMinor, t.currency)}</dd>
              </div>
              <div>
                <dt className="text-on-surface-variant">Allowance</dt>
                <dd className="m-0">
                  <span className="text-data-md">{n(t.allowanceUnits)}</span> units
                </dd>
              </div>
              <div>
                <dt className="text-on-surface-variant">Seats</dt>
                <dd className="m-0">
                  <TierSeats tier={t} />
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-on-surface-variant">Paymob plan</dt>
                <dd className="m-0">
                  <PaymobCell tier={t} />
                </dd>
              </div>
            </dl>
            <TierActions tier={t} open={open} />
          </li>
        ))}
      </ul>
    </>
  )
}

function StatusCell({ status }: { status: VersionStatus }) {
  if (status === "current") return <Badge tone="ok">In force</Badge>
  if (status === "scheduled") return <Badge tone="info">Scheduled</Badge>
  return <span className="text-body-sm text-on-surface-variant">Replaced</span>
}

/** One audience's signup credits: how many, and for how long. */
function FreeRow({ label, units, days }: { label: string; units: number | null; days: number | null }) {
  return (
    <div>
      <dt className="text-on-surface-variant">{label}</dt>
      <dd className="m-0 text-data-md">{units === null ? "Not set" : `${n(units)} units`}</dd>
      <dd className="m-0 text-body-sm text-on-surface-variant">{days === null ? "Never expires" : `Expire after ${n(days)} days`}</dd>
    </div>
  )
}

function Body({ c, open, saved }: { c: AdminCatalogue; open: (d: Dialog) => void; saved: (what: string) => () => void }) {
  const rates = versionRows(c.rates)
  const estimators = versionRows(c.estimators)
  const free = c.freeAllowances
  return (
    <div className="flex flex-col gap-10">
      <Section
        title="Plan tiers"
        hint="Prices and allowances as buyers meet them. Seat fields apply to teacher plans only."
        action={
          <Button variant="secondary" onClick={() => open({ kind: "tier", tier: null })}>
            New tier
          </Button>
        }
      >
        <Tiers tiers={c.tiers} open={open} />
      </Section>

      <Section
        title="Credit packs"
        action={
          <Button variant="secondary" onClick={() => open({ kind: "pack", pack: null })}>
            New pack
          </Button>
        }
      >
        {c.packs.length === 0 ? (
          <Empty>No credit packs yet. Create the first one.</Empty>
        ) : (
          <>
            <div className="hidden md:block">
              <Table density="operate">
                <caption className="sr-only">Credit packs</caption>
                <THead>
                  <TR>
                    <TH>Pack</TH>
                    <TH numeric>Credits</TH>
                    <TH numeric>Price</TH>
                    <TH>Sale</TH>
                    <TH>
                      <span className="sr-only">Actions</span>
                    </TH>
                  </TR>
                </THead>
                <TBody>
                  {c.packs.map((p) => (
                    <TR key={p.id}>
                      <TD>
                        <div className="flex flex-col">
                          <span>{p.name}</span>
                          <span className="text-data-sm text-on-surface-variant">{p.code}</span>
                        </div>
                      </TD>
                      <TD numeric>{n(p.units)}</TD>
                      <TD numeric>{formatMoney(p.priceMinor, p.currency)}</TD>
                      <TD>
                        <OnSale on={p.isActive} />
                      </TD>
                      <TD>
                        <Button size="sm" variant="secondary" onClick={() => open({ kind: "pack", pack: p })} aria-label={`Edit ${p.code}`}>
                          Edit
                        </Button>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
            <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 md:hidden">
              {c.packs.map((p) => (
                <li key={p.id} className="flex flex-col gap-3 rounded-lg border border-outline-variant bg-surface-container-lowest p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-col">
                      <h3 className="m-0 text-body-lg font-medium text-on-surface">{p.name}</h3>
                      <span className="text-data-sm text-on-surface-variant">{p.code}</span>
                    </div>
                    <OnSale on={p.isActive} />
                  </div>
                  <dl className="m-0 grid grid-cols-2 gap-x-4 text-body-sm">
                    <div>
                      <dt className="text-on-surface-variant">Credits</dt>
                      <dd className="m-0 text-data-md">{n(p.units)}</dd>
                    </div>
                    <div>
                      <dt className="text-on-surface-variant">Price</dt>
                      <dd className="m-0 text-data-md">{formatMoney(p.priceMinor, p.currency)}</dd>
                    </div>
                  </dl>
                  <div>
                    <Button size="sm" variant="secondary" onClick={() => open({ kind: "pack", pack: p })} aria-label={`Edit ${p.code}`}>
                      Edit
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      <Section
        title="Free allowances"
        hint="What a new account starts with. These are not for sale."
        action={
          <Button variant="secondary" onClick={() => open({ kind: "free", free })} aria-label="Edit free allowances">
            Edit
          </Button>
        }
      >
        <dl className="m-0 grid gap-x-8 gap-y-4 text-body-sm sm:grid-cols-2">
          <FreeRow label="Student free allowance" units={free.studentSignupUnits} days={free.studentSignupExpiryDays} />
          <FreeRow label="Teacher signup credits" units={free.teacherSignupUnits} days={free.teacherSignupExpiryDays} />
        </dl>
      </Section>

      <BillingRules saved={saved} />

      <CreditConversion saved={saved} />

      <Section
        title="Usage rates"
        hint="Units charged per US dollar of model cost. A version is never edited; a new one takes over from its start."
        action={
          <Button variant="secondary" onClick={() => open({ kind: "rate" })}>
            New rate version
          </Button>
        }
      >
        {rates.length === 0 ? (
          <Empty>No usage rates yet. Metered actions are not priced until one exists.</Empty>
        ) : (
          <Table density="operate" tabIndex={0} role="region" aria-label="Usage rates">
            <caption className="sr-only">Usage rates</caption>
            <THead>
              <TR>
                <TH>Action</TH>
                <TH numeric>Version</TH>
                <TH numeric>Units per USD</TH>
                <TH>Effective from</TH>
                <TH className="hidden md:table-cell">Status</TH>
              </TR>
            </THead>
            <TBody>
              {rates.map(({ row: r, status }) => (
                <TR key={r.id}>
                  <TD>
                    <div className="flex flex-col items-start gap-1">
                      <span className="text-data-sm">{r.action}</span>
                      <span className="md:hidden">
                        <StatusCell status={status} />
                      </span>
                    </div>
                  </TD>
                  <TD numeric>{r.version}</TD>
                  <TD numeric>{n(r.unitsPerUsd)}</TD>
                  <TD>{formatUtc(r.effectiveFrom)}</TD>
                  <TD className="hidden md:table-cell">
                    <StatusCell status={status} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Section>

      <Section
        title="Estimators"
        hint="The range shown before a metered action runs. Same rule: add a version, never edit one."
        action={
          <Button variant="secondary" onClick={() => open({ kind: "estimator" })}>
            New estimator version
          </Button>
        }
      >
        {estimators.length === 0 ? (
          <Empty>No estimators yet. Metered actions show no estimate until one exists.</Empty>
        ) : (
          <Table density="operate" tabIndex={0} role="region" aria-label="Estimators">
            <caption className="sr-only">Estimators</caption>
            <THead>
              <TR>
                <TH>Action</TH>
                <TH numeric>Version</TH>
                <TH>Input</TH>
                <TH numeric>Base</TH>
                <TH numeric>Per input</TH>
                <TH>Effective from</TH>
                <TH className="hidden md:table-cell">Status</TH>
              </TR>
            </THead>
            <TBody>
              {estimators.map(({ row: e, status }) => (
                <TR key={e.id}>
                  <TD>
                    <div className="flex flex-col items-start gap-1">
                      <span className="text-data-sm">{e.action}</span>
                      <span className="md:hidden">
                        <StatusCell status={status} />
                      </span>
                    </div>
                  </TD>
                  <TD numeric>{e.version}</TD>
                  <TD>{e.inputKind}</TD>
                  <TD numeric>
                    {e.baseLow}–{e.baseHigh}
                  </TD>
                  <TD numeric>
                    {e.perInputLow}–{e.perInputHigh}
                  </TD>
                  <TD>{formatUtc(e.effectiveFrom)}</TD>
                  <TD className="hidden md:table-cell">
                    <StatusCell status={status} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Section>

      <LlmPrices saved={saved} />
    </div>
  )
}

export function Catalogue() {
  const catalogue = useAdminCatalogue()
  const createTier = useCreateTier()
  const updateTier = useUpdateTier()
  const syncTier = useSyncTier()
  const createPack = useCreatePack()
  const updatePack = useUpdatePack()
  const createRate = useCreateRate()
  const createEstimator = useCreateEstimator()
  const updateFree = useUpdateFreeAllowances()
  const [dialog, setDialog] = useState<Dialog>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const close = () => setDialog(null)
  const open = (d: Dialog) => {
    setNotice(null)
    setDialog(d)
  }
  const saved = (what: string) => () => setNotice(`${what} The change and your reason are in the audit log.`)

  if (catalogue.status === "error" && isForbidden(catalogue.error)) {
    return <ErrorState kicker={null} heading="You can't open the billing catalogue" body="Billing is for platform admins. Ask one to change prices or allowances." />
  }

  return (
    <QueryState
      query={catalogue}
      skeleton={
        <div className="flex flex-col gap-10">
          <ListSkeleton rows={3} />
          <ListSkeleton rows={2} />
          <ListSkeleton rows={3} />
        </div>
      }
      error={{ heading: "Couldn't load the catalogue" }}
    >
      {(c) => (
        <>
          <div role="status" className={notice ? "mb-6 rounded-md bg-surface-container-low px-4 py-3 text-body-sm text-on-surface" : "sr-only"}>
            {notice}
          </div>
          <Body c={c} open={open} saved={saved} />
          {dialog?.kind === "tier" ? (
            dialog.tier ? (
              <ReasonedFormDialog
                key={dialog.tier.id}
                open
                onClose={close}
                title={`Edit ${dialog.tier.code}`}
                fields={TIER_UPDATE_FIELDS}
                initial={tierValues(dialog.tier)}
                submitLabel="Save tier"
                mutation={updateTier}
                toBody={(v, r) => ({ id: dialog.tier!.id, body: tierUpdateBody(v, r, dialog.tier!.rawFeatures) })}
                note={
                  <p className="m-0 text-body-sm text-on-surface-variant">
                    Code, audience and interval are fixed once a tier exists. A changed price shows as drift until it is synced to Paymob.
                    {hiddenFeatureCount(dialog.tier.rawFeatures) > 0
                      ? ` ${hiddenFeatureCount(dialog.tier.rawFeatures)} other feature setting${hiddenFeatureCount(dialog.tier.rawFeatures) === 1 ? "" : "s"} on this tier are not lines to edit and are kept as they are.`
                      : ""}
                  </p>
                }
                onSaved={saved(`Saved ${dialog.tier.code}.`)}
              />
            ) : (
              <ReasonedFormDialog
                open
                onClose={close}
                title="New plan tier"
                fields={TIER_FIELDS}
                initial={tierValues(null)}
                submitLabel="Create tier"
                mutation={createTier}
                toBody={tierBody}
                onSaved={saved("Created the tier.")}
              />
            )
          ) : null}
          {dialog?.kind === "sync" ? (
            <ReasonedFormDialog
              open
              onClose={close}
              title={`Sync ${dialog.tier.code} to Paymob`}
              fields={[]}
              initial={{}}
              submitLabel={dialog.tier.drift === null ? "Create a new plan anyway" : "Sync to Paymob"}
              mutation={syncTier}
              toBody={(_v, r) => ({ id: dialog.tier.id, body: { reason: r } })}
              rolledBackOn502
              note={
                <div className="flex flex-col gap-2 text-body-sm text-on-surface">
                  <p className="m-0">
                    Creates a new Paymob plan at {formatMoney(dialog.tier.priceMinor, dialog.tier.currency)} {intervalWord(dialog.tier)} and links this tier to it. New checkouts use the new plan.
                    Subscriptions already running keep the plan they started on. If Paymob does not accept it, nothing changes.
                  </p>
                  {dialog.tier.drift === null ? (
                    <p className="m-0 text-on-surface-variant">
                      This tier is already in sync. Syncing again only adds another plan in Paymob
                      {dialog.tier.paymobPlanId === null ? "" : ` and replaces plan ${dialog.tier.paymobPlanId} as the tier's link`}. Do it after changing the price or interval, not otherwise.
                    </p>
                  ) : null}
                </div>
              }
              onSaved={saved(`Synced ${dialog.tier.code} to Paymob.`)}
            />
          ) : null}
          {dialog?.kind === "pack" ? (
            dialog.pack ? (
              <ReasonedFormDialog
                key={dialog.pack.id}
                open
                onClose={close}
                title={`Edit ${dialog.pack.code}`}
                fields={PACK_UPDATE_FIELDS}
                initial={packValues(dialog.pack)}
                submitLabel="Save pack"
                mutation={updatePack}
                toBody={(v, r) => ({ id: dialog.pack!.id, body: packUpdateBody(v, r) })}
                note={<p className="m-0 text-body-sm text-on-surface-variant">The code is fixed once a pack exists.</p>}
                onSaved={saved(`Saved ${dialog.pack.code}.`)}
              />
            ) : (
              <ReasonedFormDialog
                open
                onClose={close}
                title="New credit pack"
                fields={PACK_FIELDS}
                initial={packValues(null)}
                submitLabel="Create pack"
                mutation={createPack}
                toBody={packBody}
                onSaved={saved("Created the pack.")}
              />
            )
          ) : null}
          {dialog?.kind === "rate" ? (
            <ReasonedFormDialog
              open
              onClose={close}
              title="New usage rate version"
              fields={RATE_FIELDS}
              initial={{ action: "mark_paper", unitsPerUsd: "", effectiveFrom: "" }}
              submitLabel="Create version"
              mutation={createRate}
              toBody={rateBody}
              onSaved={saved("Added the rate version.")}
            />
          ) : null}
          {dialog?.kind === "estimator" ? (
            <ReasonedFormDialog
              open
              onClose={close}
              title="New estimator version"
              fields={ESTIMATOR_FIELDS}
              initial={{ action: "mark_paper", inputKind: "none", baseLow: "", baseHigh: "", perInputLow: "0", perInputHigh: "0", effectiveFrom: "" }}
              submitLabel="Create version"
              mutation={createEstimator}
              toBody={estimatorBody}
              check={estimatorErrors}
              onSaved={saved("Added the estimator version.")}
            />
          ) : null}
          {dialog?.kind === "free" ? (
            <ReasonedFormDialog
              open
              onClose={close}
              title="Free allowances"
              fields={FREE_FIELDS}
              initial={freeValues(dialog.free)}
              submitLabel="Save allowances"
              mutation={updateFree}
              toBody={(v, r) => freeChanges(v, r, dialog.free)}
              check={(v) => (freeChanges(v, "unused", dialog.free).length === 0 ? ["Nothing has changed. Change a value to save."] : [])}
              blocked={staleBlock(updateFree.error)}
              reload="Reload this page"
              onSaved={saved("Saved the free allowances.")}
            />
          ) : null}
        </>
      )}
    </QueryState>
  )
}

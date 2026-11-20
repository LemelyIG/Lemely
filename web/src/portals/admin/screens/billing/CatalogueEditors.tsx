/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import {
  PACK_UPDATE_FIELDS,
  TIER_UPDATE_FIELDS,
  hiddenFeatureCount,
  packUpdateBody,
  packValues,
  tierUpdateBody,
  tierValues,
  type FormValues,
} from "@/lib/adminBillingModel"
import { staleBlock } from "@/lib/adminRatesModel"
import type { AdminCreditPack, AdminPlanTier } from "@/lib/billingTypes"
import { packImpactLines, packPriceTarget, tierImpact, tierImpactLines } from "@/lib/catalogueImpact"
import { useDebouncedValue } from "@/lib/hooks/useDebouncedValue"
import { usePackPriceImpact, type useUpdatePack, type useUpdateTier } from "@/lib/hooks/useAdminBillingApi"
import { ReasonedFormDialog, type ImpactView } from "./ReasonedFormDialog"

/*
 * The two edit dialogs that touch customers who already pay. Each is built from the row it was
 * opened on: the version it sends and the baseline its warning compares against stay fixed
 * while the catalogue refetches behind it, so what the admin typed never goes out under a newer
 * version than the one they read. A stale write blocks a second submit until the dialog is
 * closed and the row opened again.
 */

const NO_WARNING: ImpactView = { warned: false, node: null, confirmLabel: "", key: "" }
const PACK_CONFIRM = "I understand these customers will be charged the new price."
const PACK_UNKNOWN_CONFIRM = "I understand I can't see who is affected, and they will be charged the new price."
const TIER_CONFIRM = "I understand these customers will be emailed about the change."

const lines = (items: string[]) => items.map((t) => <p key={t} className="m-0">{t}</p>)

export function TierEditDialog({
  tier,
  noticeDays,
  amountUpdatable,
  mutation,
  onClose,
  onSaved,
}: {
  tier: AdminPlanTier
  noticeDays: number
  amountUpdatable: boolean
  mutation: ReturnType<typeof useUpdateTier>
  onClose: () => void
  onSaved: () => void
}) {
  const hidden = hiddenFeatureCount(tier.rawFeatures)
  const useTierImpact = (values: FormValues): ImpactView => {
    const impact = tierImpact(tier, values, { noticeDays, amountUpdatable })
    if (!impact) return NO_WARNING
    const text = tierImpactLines(impact)
    return { warned: true, node: lines(text), confirmLabel: TIER_CONFIRM, key: text.join("\n") }
  }
  return (
    <ReasonedFormDialog
      open
      onClose={onClose}
      title={`Edit ${tier.code}`}
      fields={TIER_UPDATE_FIELDS}
      initial={tierValues(tier)}
      submitLabel="Save tier"
      mutation={mutation}
      toBody={(v, r) => ({ id: tier.id, body: tierUpdateBody(v, r, tier.rawFeatures, tier.version) })}
      blocked={staleBlock(mutation.error)}
      reload="Reload this page"
      useImpact={useTierImpact}
      note={
        <p className="m-0 text-body-sm text-on-surface-variant">
          Code, audience and interval are fixed once a tier exists. A changed price shows as drift until it is synced to Paymob.
          {hidden > 0 ? ` ${hidden} other feature setting${hidden === 1 ? "" : "s"} on this tier are not lines to edit and are kept as they are.` : ""}
        </p>
      }
      onSaved={onSaved}
    />
  )
}

/** What the preview says about the typed price: asked after a pause, never for a price the server refuses. */
function usePackImpactView(pack: AdminCreditPack, values: FormValues): ImpactView {
  const target = packPriceTarget(pack, values)
  const settled = useDebouncedValue(target, 350)
  const query = usePackPriceImpact(pack.id, settled)
  if (target === null) return NO_WARNING
  const warning = (node: ImpactView["node"], key: string, pending = false, confirmLabel = PACK_CONFIRM): ImpactView => ({ warned: true, node, confirmLabel, key, pending })
  // The counts are not known yet: nothing can be confirmed, and the save waits.
  if (settled !== target || query.isPending) return warning(<p className="m-0">Checking who this affects…</p>, "pending", true)
  // A failed count gets its own confirm: the admin is told they cannot see who is affected.
  if (query.isError) return warning(<p className="m-0">Couldn&apos;t check how many auto top-ups this affects. They will be charged the new price.</p>, "unknown", false, PACK_UNKNOWN_CONFIRM)
  const impact = packImpactLines(query.data)
  return impact === null ? NO_WARNING : warning(lines(impact), impact.join("\n"))
}

export function PackEditDialog({
  pack,
  mutation,
  onClose,
  onSaved,
}: {
  pack: AdminCreditPack
  mutation: ReturnType<typeof useUpdatePack>
  onClose: () => void
  onSaved: () => void
}) {
  const usePackImpact = (values: FormValues): ImpactView => usePackImpactView(pack, values)
  return (
    <ReasonedFormDialog
      open
      onClose={onClose}
      title={`Edit ${pack.code}`}
      fields={PACK_UPDATE_FIELDS}
      initial={packValues(pack)}
      submitLabel="Save pack"
      mutation={mutation}
      toBody={(v, r) => ({ id: pack.id, body: packUpdateBody(v, r, pack.version) })}
      blocked={staleBlock(mutation.error)}
      reload="Reload this page"
      useImpact={usePackImpact}
      note={<p className="m-0 text-body-sm text-on-surface-variant">The code is fixed once a pack exists.</p>}
      onSaved={onSaved}
    />
  )
}

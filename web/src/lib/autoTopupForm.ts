import { formatMoney } from "@/lib/billingFormat"
import type { AutoTopupSettings, AutoTopupUpdate, CreditPack } from "@/lib/billingTypes"

/* Auto top-up form state, validation and wire conversion. Numbers are kept as strings while
 * editing so a half-typed value is not coerced under the user's cursor. */

export interface AutoTopupFormState {
  enabled: boolean
  thresholdUnits: string
  creditPackId: string | null
  savedCardId: string | null
  /** EGP, as typed. Sent as piasters. */
  monthlyCapMajor: string
}

/** "Not set up" (06: `enabled: false` and nulls) becomes empty fields. */
export function formFromSettings(settings: AutoTopupSettings): AutoTopupFormState {
  return {
    enabled: settings.enabled,
    thresholdUnits: settings.thresholdUnits === null ? "" : String(settings.thresholdUnits),
    creditPackId: settings.creditPackId,
    savedCardId: settings.savedCardId,
    monthlyCapMajor: settings.monthlyCapMinor === null ? "" : String(settings.monthlyCapMinor / 100),
  }
}

function capMinor(form: AutoTopupFormState): number {
  return Math.round((Number(form.monthlyCapMajor) || 0) * 100)
}

/** 06 `AutoTopupRequest` needs a pack and a positive threshold on every save. */
export function validateAutoTopup(form: AutoTopupFormState, packs: CreditPack[]): string[] {
  const errors: string[] = []
  const pack = packs.find((p) => p.id === form.creditPackId) ?? null
  if (!pack) errors.push("Choose a pack to buy.")
  if (!(Number(form.thresholdUnits) >= 1)) errors.push("Set a threshold of at least 1 credit.")
  if (!form.enabled) return errors
  if (!form.savedCardId) errors.push("Choose a saved card.")
  if (pack && capMinor(form) < pack.priceMinor) {
    errors.push(`The monthly limit must cover at least one pack (${formatMoney(pack.priceMinor, pack.currency)}).`)
  }
  return errors
}

export function toUpdate(form: AutoTopupFormState, beneficiaryId: string | null): AutoTopupUpdate {
  return {
    beneficiaryId,
    enabled: form.enabled,
    thresholdUnits: Math.max(1, Math.floor(Number(form.thresholdUnits) || 1)),
    // `validateAutoTopup` refuses a save without a pack, so this is never "" on the wire.
    creditPackId: form.creditPackId ?? "",
    savedCardId: form.savedCardId,
    monthlyCapMinor: capMinor(form),
  }
}

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

/** "Not set up" (06: `enabled: false` and nulls) becomes empty fields. A saved cap of 0 is the
 * placeholder a switched-off save sends when no limit was ever typed, so it shows as empty too. */
export function formFromSettings(settings: AutoTopupSettings): AutoTopupFormState {
  return {
    enabled: settings.enabled,
    thresholdUnits: settings.thresholdUnits === null ? "" : String(settings.thresholdUnits),
    creditPackId: settings.creditPackId,
    savedCardId: settings.savedCardId,
    monthlyCapMajor: settings.monthlyCapMinor ? String(settings.monthlyCapMinor / 100) : "",
  }
}

function capMinor(form: AutoTopupFormState): number {
  return Math.round((Number(form.monthlyCapMajor) || 0) * 100)
}

export type AutoTopupField = "creditPackId" | "thresholdUnits" | "savedCardId" | "monthlyCapMajor"

/** The error for each invalid field, in the order the fields sit on the page. 06
 * `AutoTopupRequest` needs a pack and a positive threshold on every save; the cap is mandatory
 * once top-up is on (06 requires `monthlyCapMinor`, and the spec makes the charge subject to it). */
export function fieldErrors(form: AutoTopupFormState, packs: CreditPack[]): Partial<Record<AutoTopupField, string>> {
  const errors: Partial<Record<AutoTopupField, string>> = {}
  const pack = packs.find((p) => p.id === form.creditPackId) ?? null
  if (!pack) errors.creditPackId = "Choose a pack to buy."
  if (!(Number(form.thresholdUnits) >= 1)) errors.thresholdUnits = "Set a threshold of at least 1 credit."
  if (!form.enabled) return errors
  if (!form.savedCardId) errors.savedCardId = "Choose a saved card."
  if (form.monthlyCapMajor.trim() === "") {
    errors.monthlyCapMajor = "Set a monthly limit."
  } else if (pack && capMinor(form) < pack.priceMinor) {
    errors.monthlyCapMajor = `The monthly limit must cover at least one pack (${formatMoney(pack.priceMinor, pack.currency)}).`
  }
  return errors
}

const FIELD_ORDER: AutoTopupField[] = ["creditPackId", "thresholdUnits", "savedCardId", "monthlyCapMajor"]

export function validateAutoTopup(form: AutoTopupFormState, packs: CreditPack[]): string[] {
  const errors = fieldErrors(form, packs)
  return FIELD_ORDER.flatMap((f) => errors[f] ?? [])
}

/** `savedCapMinor` is what the server last stored: a switched-off save with no cap typed keeps
 * it (or sends 0 when there was none) rather than inventing a limit. */
export function toUpdate(form: AutoTopupFormState, beneficiaryId: string | null, savedCapMinor: number | null = null): AutoTopupUpdate {
  const cap = form.monthlyCapMajor.trim() === "" && !form.enabled ? (savedCapMinor ?? 0) : capMinor(form)
  return {
    beneficiaryId,
    enabled: form.enabled,
    thresholdUnits: Math.max(1, Math.floor(Number(form.thresholdUnits) || 1)),
    // `validateAutoTopup` refuses a save without a pack, so this is never "" on the wire.
    creditPackId: form.creditPackId ?? "",
    savedCardId: form.savedCardId,
    monthlyCapMinor: cap,
  }
}

function sameForm(a: AutoTopupFormState, b: AutoTopupFormState): boolean {
  return (
    a.enabled === b.enabled &&
    a.thresholdUnits === b.thresholdUnits &&
    a.creditPackId === b.creditPackId &&
    a.savedCardId === b.savedCardId &&
    a.monthlyCapMajor === b.monthlyCapMajor
  )
}

export function isPristine(form: AutoTopupFormState, baseline: AutoTopupFormState): boolean {
  return sameForm(form, baseline)
}

/** The form is not remounted when the server copy changes (a save, or a background refetch of
 * `spentThisMonthMinor`). It adopts the new server values only while the user has not edited
 * anything since the last adoption; otherwise their in-progress edits stand. */
export function reconcileForm(
  form: AutoTopupFormState,
  baseline: AutoTopupFormState,
  server: AutoTopupFormState,
): { form: AutoTopupFormState; baseline: AutoTopupFormState } {
  if (sameForm(server, baseline)) return { form, baseline }
  return { form: sameForm(form, baseline) ? server : form, baseline: server }
}

/** Everything the card remembers between renders. `baseline` is the last server copy the form
 * adopted or was saved as; `saved` is "a save just succeeded and nothing was touched since". */
export interface AutoTopupState {
  form: AutoTopupFormState
  baseline: AutoTopupFormState
  saved: boolean
}

export type AutoTopupEvent =
  | { type: "serverSettings"; server: AutoTopupFormState }
  | { type: "edit"; patch: Partial<AutoTopupFormState> }
  | { type: "saveSucceeded"; saved: AutoTopupFormState }
  | { type: "saveFailed" }

export function initialState(server: AutoTopupFormState): AutoTopupState {
  return { form: server, baseline: server, saved: false }
}

export function autoTopupReducer(state: AutoTopupState, event: AutoTopupEvent): AutoTopupState {
  switch (event.type) {
    case "serverSettings":
      return { ...state, ...reconcileForm(state.form, state.baseline, event.server) }
    case "edit":
      // Any edit retires "Saved.", so editing and reverting never brings it back.
      return { ...state, form: { ...state.form, ...event.patch }, saved: false }
    case "saveSucceeded":
      return { form: event.saved, baseline: event.saved, saved: true }
    case "saveFailed":
      return { ...state, saved: false }
  }
}

/** Show "Saved." only while the form still matches what was saved. */
export function showSaved(state: AutoTopupState): boolean {
  return state.saved && isPristine(state.form, state.baseline)
}

/** Top-up can always be switched off; switching it on needs a saved card. */
export function switchDisabled(form: AutoTopupFormState, hasCard: boolean): boolean {
  return !hasCard && !form.enabled
}
const KNOWN_DISABLED_REASON = "charge_failed"

/** What to say when the server switched top-up off itself. */
export function disabledNotice(reason: string | null): "charge_failed" | "other" | null {
  if (reason === null) return null
  return reason === KNOWN_DISABLED_REASON ? "charge_failed" : "other"
}

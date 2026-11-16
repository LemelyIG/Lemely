import { billingErrorCode } from "@/lib/billingOutcome"
import type { FieldSpec, FormValues } from "@/lib/adminBillingModel"
import type {
  BillingSettings,
  BillingSettingsUpdate,
  CreditRate,
  CreditRateClear,
  CreditRateSet,
  LlmModelPrice,
  LlmPriceClear,
  LlmPriceSet,
} from "@/lib/billingTypes"

/* Pure form models for the rate panels of the billing catalogue: billing rules (07 T14
 * `/settings`), credit conversion (`/credit-rates`) and AI token prices (T19 `/llm-prices`).
 * Bodies match `lemely/web/schemas_admin_billing_settings.py`. Ranges mirror
 * `billing_settings_repo.validate_settings`; the server stays the authority and a refusal shows
 * its own sentence. */

const str = (v: FormValues, k: string) => String(v[k] ?? "").trim()

/** `"3.500000"` as `"3.5"`, `"50.0"` as `"50"`: the form compares and shows decimals without padding. */
export function trimDecimal(text: string): string {
  const t = text.trim()
  if (!t.includes(".")) return t
  return t.replace(/0+$/, "").replace(/\.$/, "")
}

const GROUP = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 })

/** Whole part grouped, decimals as given: exact for strings the API sends, never through a float. */
function groupedDecimal(text: string): string {
  const [whole = "0", frac] = trimDecimal(text).split(".")
  const g = GROUP.format(Number(whole))
  return frac ? `${g}.${frac}` : g
}

/** Move the decimal point right by `places` digits in the text, no float involved. */
export function shiftDecimal(text: string, places: number): string {
  const [whole = "0", frac = ""] = text.trim().split(".")
  const padded = frac.padEnd(places, "0")
  const joined = `${whole}${padded.slice(0, places)}`.replace(/^0+(?=\d)/, "")
  const rest = padded.slice(places)
  return trimDecimal(rest === "" ? joined : `${joined}.${rest}`)
}

/** "1 EGP = 12.5 units" from the rate per piaster (1 EGP is 100 piasters). */
export function unitsPerMajor(unitsPerMinor: string): string {
  return groupedDecimal(shiftDecimal(unitsPerMinor, 2))
}

export function unitsPerMinorText(unitsPerMinor: string): string {
  return groupedDecimal(unitsPerMinor)
}

/** A USD per million tokens price: two decimals at least, more only when the price needs them. */
export function usdPerMtok(text: string | null): string {
  if (text === null) return "None"
  const t = trimDecimal(text)
  const [whole = "0", frac = ""] = t.split(".")
  return `$${GROUP.format(Number(whole))}.${frac.padEnd(2, "0")}`
}

/** The server answers a stale or duplicate write with one of these: the section must reload. */
const RELOAD_CODES = new Set(["stale_write", "credit_rate_exists", "credit_rate_not_set", "llm_price_exists", "llm_price_not_set"])

export function isStaleWrite(error: unknown): boolean {
  const code = billingErrorCode(error)
  return code !== null && RELOAD_CODES.has(code)
}

/** A refused write whose form was built on old data must not offer the same submit again. */
export function staleBlock(error: unknown): string | null {
  return isStaleWrite(error) ? "Reloaded with the current values." : null
}

// ── Billing rules ───────────────────────────────────────────────────────────

export const SETTINGS_FIELDS: FieldSpec[] = [
  { name: "creditValidityMonths", label: "Credit validity (months)", kind: "number", min: 1, max: 120, hint: "How long bought credits last. 1 to 120." },
  {
    name: "graceDays",
    label: "Grace days",
    kind: "number",
    min: 1,
    max: 7,
    hint: "Also sets how many days Paymob retries a failed renewal on newly synced plans. 1 to 7.",
  },
  {
    name: "priceChangeNoticeDays",
    label: "Price-change notice (days)",
    kind: "number",
    min: 7,
    max: 90,
    hint: "Customers on a plan whose price or terms get worse are emailed this many days before they move. 7 to 90.",
  },
  { name: "maxExtraSeats", label: "Extra-seat ceiling", kind: "number", min: 1, max: 10_000, hint: "Most extra seats one teacher can hold. 1 to 10,000." },
  { name: "marginEgpPerUsd", label: "Margin rate (EGP per USD)", kind: "decimal", optional: true, places: 4, max: 10_000, hint: "Default rate for margin reports. Empty means none." },
  {
    name: "codeExecutionUsdPerHour",
    label: "Code execution (USD per container hour)",
    kind: "decimal",
    optional: true,
    places: 6,
    max: 10_000,
    hint: "Empty means the built-in rate.",
  },
  {
    name: "confirmUnusualPrice",
    label: "This price is right. Set it anyway",
    kind: "checkbox",
    showWhen: (_v, error) => billingErrorCode(error) === "unusual_price",
  },
]

export function settingsValues(s: BillingSettings): FormValues {
  return {
    creditValidityMonths: String(s.creditValidityMonths),
    graceDays: String(s.graceDays),
    priceChangeNoticeDays: String(s.priceChangeNoticeDays),
    maxExtraSeats: String(s.maxExtraSeats),
    marginEgpPerUsd: s.marginEgpPerUsd === null ? "" : trimDecimal(s.marginEgpPerUsd),
    codeExecutionUsdPerHour: s.codeExecutionUsdPerHour === null ? "" : trimDecimal(s.codeExecutionUsdPerHour),
    confirmUnusualPrice: false,
  }
}

const INT_SETTINGS = ["creditValidityMonths", "graceDays", "priceChangeNoticeDays", "maxExtraSeats"] as const
const DECIMAL_SETTINGS = ["marginEgpPerUsd", "codeExecutionUsdPerHour"] as const

/** Only what differs from `current`, plus the version read and the reason. Empty decimal = clear. */
export function settingsChanges(v: FormValues, current: BillingSettings): Omit<BillingSettingsUpdate, "reason" | "expectedVersion"> {
  const changes: Omit<BillingSettingsUpdate, "reason" | "expectedVersion"> = {}
  for (const k of INT_SETTINGS) if (Number(str(v, k)) !== current[k]) changes[k] = Number(str(v, k))
  for (const k of DECIMAL_SETTINGS) {
    const typed = trimDecimal(str(v, k))
    const stored = current[k] === null ? "" : trimDecimal(current[k])
    if (typed !== stored) changes[k] = typed === "" ? null : typed
  }
  if (v.confirmUnusualPrice === true && changes.codeExecutionUsdPerHour !== undefined) changes.confirmUnusualPrice = true
  return changes
}

export function settingsBody(v: FormValues, reason: string, current: BillingSettings): BillingSettingsUpdate {
  return { ...settingsChanges(v, current), expectedVersion: current.version, reason }
}

export function settingsNothingChanged(v: FormValues, current: BillingSettings): string[] {
  const c = settingsChanges(v, current)
  return Object.keys(c).filter((k) => k !== "confirmUnusualPrice").length === 0 ? ["Nothing has changed. Change a value to save."] : []
}

// ── Credit conversion ───────────────────────────────────────────────────────

export const CREDIT_RATE_FIELDS: FieldSpec[] = [
  {
    name: "unitsPerMinor",
    label: "Units per piaster",
    kind: "decimal",
    places: 6,
    max: 1_000_000,
    hint: "Credits a customer gets for each piaster paid. 1 EGP is 100 piasters.",
  },
]

export function creditRateValues(rate: CreditRate | null): FormValues {
  return { unitsPerMinor: rate === null ? "" : trimDecimal(rate.unitsPerMinor) }
}

export function creditRateSetBody(v: FormValues, reason: string, rate: CreditRate | null): CreditRateSet {
  return { unitsPerMinor: str(v, "unitsPerMinor"), expectedVersion: rate?.version ?? null, reason }
}

export function creditRateUnchanged(v: FormValues, rate: CreditRate | null): string[] {
  return rate !== null && trimDecimal(str(v, "unitsPerMinor")) === trimDecimal(rate.unitsPerMinor) ? ["Nothing has changed. Change the rate to save."] : []
}

/** Clearing stops conversions, so the body always carries the confirmation the server demands. */
export function creditRateClearBody(reason: string, rate: CreditRate): CreditRateClear {
  return { expectedVersion: rate.version, confirmStopConversions: true, reason }
}

// ── AI token prices ─────────────────────────────────────────────────────────

const PRICE_MAX = 1000
const RATE_FIELD_NAMES = [
  "inputUsdPerMtok",
  "outputUsdPerMtok",
  "cachedInputUsdPerMtok",
  "cacheWrite5mUsdPerMtok",
  "cacheWrite1hUsdPerMtok",
  "tier2InputUsdPerMtok",
  "tier2OutputUsdPerMtok",
] as const
type RateName = (typeof RATE_FIELD_NAMES)[number]

/** Below 1/100 or above 100 times the default: the server's own "unit typo" line. */
const UNUSUAL_FACTOR = 100

/** The rates the form holds that are far from the model's built-in ones (none when it has none). */
export function unusualRateNames(v: FormValues, model: LlmModelPrice): RateName[] {
  const d = model.codeDefault
  if (d === null) return []
  return RATE_FIELD_NAMES.filter((k) => {
    const typed = str(v, k)
    const base = d[k]
    if (typed === "" || base === null || Number(base) <= 0 || !/^\d+(\.\d+)?$/.test(typed)) return false
    const n = Number(typed)
    return n < Number(base) / UNUSUAL_FACTOR || n > Number(base) * UNUSUAL_FACTOR
  })
}

/** The built-in price is tiered and this override has no tier 2 prices: one flat rate at every length. */
export function dropsTier(v: FormValues, model: LlmModelPrice): boolean {
  return model.codeDefault?.tiered === true && str(v, "tier2InputUsdPerMtok") === "" && str(v, "tier2OutputUsdPerMtok") === "" && str(v, "tierThresholdTokens") === ""
}

export function llmPriceFields(model: LlmModelPrice): FieldSpec[] {
  const rate = (name: RateName, label: string, optional: boolean, hint?: string): FieldSpec => ({
    name,
    label,
    kind: "decimal",
    optional,
    places: 6,
    max: PRICE_MAX,
    hint,
  })
  return [
    rate("inputUsdPerMtok", "Input (USD per million tokens)", false),
    rate("outputUsdPerMtok", "Output (USD per million tokens)", false),
    rate("cachedInputUsdPerMtok", "Cached input", true, "Empty uses the built-in rate."),
    rate("cacheWrite5mUsdPerMtok", "Cache write, 5 minutes", true),
    rate("cacheWrite1hUsdPerMtok", "Cache write, 1 hour", true),
    { name: "tierThresholdTokens", label: "Tier 2 starts above (input tokens)", kind: "number", optional: true, positive: true, hint: "Tier fields go together, or all stay empty." },
    rate("tier2InputUsdPerMtok", "Tier 2 input", true, "Cache prices in tier 2 scale with this: tier 2 input ÷ input."),
    rate("tier2OutputUsdPerMtok", "Tier 2 output", true),
    {
      kind: "notice",
      name: "dropsTierNotice",
      label: "",
      text: "This override charges the same rate at every prompt length.",
      showWhen: (v) => dropsTier(v, model),
    },
    {
      name: "confirmDropTier",
      label: "Charge one flat rate at every length",
      kind: "checkbox",
      showWhen: (v, error) => dropsTier(v, model) || billingErrorCode(error) === "override_drops_tier",
    },
    {
      name: "confirmUnusualPrice",
      label: "These prices are right. Set them anyway",
      kind: "checkbox",
      showWhen: (v, error) => unusualRateNames(v, model).length > 0 || billingErrorCode(error) === "unusual_price",
    },
  ]
}

export function llmPriceValues(model: LlmModelPrice): FormValues {
  const src = model.override ?? model.codeDefault
  const text = (s: string | null | undefined) => (s === null || s === undefined ? "" : trimDecimal(s))
  return {
    inputUsdPerMtok: text(src?.inputUsdPerMtok),
    outputUsdPerMtok: text(src?.outputUsdPerMtok),
    cachedInputUsdPerMtok: text(src?.cachedInputUsdPerMtok),
    cacheWrite5mUsdPerMtok: text(src?.cacheWrite5mUsdPerMtok),
    cacheWrite1hUsdPerMtok: text(src?.cacheWrite1hUsdPerMtok),
    tierThresholdTokens: src?.tierThresholdTokens == null ? "" : String(src.tierThresholdTokens),
    tier2InputUsdPerMtok: text(src?.tier2InputUsdPerMtok),
    tier2OutputUsdPerMtok: text(src?.tier2OutputUsdPerMtok),
    confirmDropTier: false,
    confirmUnusualPrice: false,
  }
}

/** The tier trio is all set or all empty, and the pair of tier prices needs an input price to scale by. */
export function llmPriceChecks(v: FormValues): string[] {
  const trio = ["tierThresholdTokens", "tier2InputUsdPerMtok", "tier2OutputUsdPerMtok"].map((k) => str(v, k) !== "")
  if (trio.some(Boolean) && !trio.every(Boolean)) return ["Set the tier 2 start and both tier 2 prices together, or leave all three empty."]
  return []
}

/** Confirmations the form shows must be ticked before saving. */
export function llmConfirmChecks(v: FormValues, model: LlmModelPrice): string[] {
  const out: string[] = []
  if (dropsTier(v, model) && v.confirmDropTier !== true) out.push("Tick the box to charge one flat rate at every prompt length, or add the tier 2 prices.")
  if (unusualRateNames(v, model).length > 0 && v.confirmUnusualPrice !== true) out.push("A price is under 1/100 or over 100 times the built-in one. Fix a typo, or tick the box to set it anyway.")
  return out
}

const orNull = (v: FormValues, k: string) => (str(v, k) === "" ? null : trimDecimal(str(v, k)))

export function llmPriceBody(v: FormValues, reason: string, model: LlmModelPrice): LlmPriceSet {
  const body: LlmPriceSet = {
    inputUsdPerMtok: trimDecimal(str(v, "inputUsdPerMtok")),
    outputUsdPerMtok: trimDecimal(str(v, "outputUsdPerMtok")),
    cachedInputUsdPerMtok: orNull(v, "cachedInputUsdPerMtok"),
    cacheWrite5mUsdPerMtok: orNull(v, "cacheWrite5mUsdPerMtok"),
    cacheWrite1hUsdPerMtok: orNull(v, "cacheWrite1hUsdPerMtok"),
    tierThresholdTokens: str(v, "tierThresholdTokens") === "" ? null : Number(str(v, "tierThresholdTokens")),
    tier2InputUsdPerMtok: orNull(v, "tier2InputUsdPerMtok"),
    tier2OutputUsdPerMtok: orNull(v, "tier2OutputUsdPerMtok"),
    expectedVersion: model.override?.version ?? null,
    reason,
  }
  if (v.confirmDropTier === true && dropsTier(v, model)) body.confirmDropTier = true
  if (v.confirmUnusualPrice === true) body.confirmUnusualPrice = true
  return body
}

export function llmPriceClearBody(reason: string, override: { version: number }): LlmPriceClear {
  return { expectedVersion: override.version, reason }
}

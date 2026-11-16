import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { adminBillingFailureMessage, fieldErrors, visibleFields } from "@/lib/adminBillingModel"
import {
  CREDIT_RATE_FIELDS,
  SETTINGS_FIELDS,
  creditRateClearBody,
  creditRateSetBody,
  creditRateUnchanged,
  creditRateValues,
  dropsTier,
  isStaleWrite,
  llmConfirmChecks,
  llmPriceBody,
  llmPriceChecks,
  llmPriceClearBody,
  llmPriceFields,
  llmPriceValues,
  settingsBody,
  settingsNothingChanged,
  settingsValues,
  shiftDecimal,
  staleBlock,
  trimDecimal,
  unitsPerMajor,
  unusualRateNames,
  usdPerMtok,
} from "@/lib/adminRatesModel"
import { fx } from "./support/billingFixtures"

const settings = fx.billingSettings
const [tiered, flat, unpriced] = fx.llmModels
const api = (status: number, code: string) => new ApiError(status, "x", { code, message: "m" })

describe("billing rules form", () => {
  const errs = (over: Record<string, string>) => fieldErrors(SETTINGS_FIELDS, { ...settingsValues(settings), ...over })

  it("holds each setting to the server's range", () => {
    expect(errs({})).toEqual({})
    expect(errs({ creditValidityMonths: "0" }).creditValidityMonths).toMatch(/from 1 to 120/)
    expect(errs({ creditValidityMonths: "121" }).creditValidityMonths).toMatch(/from 1 to 120/)
    expect(errs({ graceDays: "8" }).graceDays).toMatch(/from 1 to 7/)
    expect(errs({ graceDays: "0" }).graceDays).toMatch(/from 1 to 7/)
    expect(errs({ priceChangeNoticeDays: "6" }).priceChangeNoticeDays).toMatch(/from 7 to 90/)
    expect(errs({ priceChangeNoticeDays: "91" }).priceChangeNoticeDays).toMatch(/from 7 to 90/)
    expect(errs({ maxExtraSeats: "10001" }).maxExtraSeats).toMatch(/from 1 to 10,000/)
    expect(errs({ maxExtraSeats: "10000", graceDays: "7", priceChangeNoticeDays: "90", creditValidityMonths: "120" })).toEqual({})
    expect(errs({ graceDays: "2.5" }).graceDays).toMatch(/whole number/)
  })

  it("lets the two decimals be empty, and refuses a bad one", () => {
    expect(errs({ marginEgpPerUsd: "", codeExecutionUsdPerHour: "" })).toEqual({})
    expect(errs({ marginEgpPerUsd: "50.12345" }).marginEgpPerUsd).toMatch(/at most 4 decimal places/)
    expect(errs({ marginEgpPerUsd: "0" }).marginEgpPerUsd).toMatch(/above 0/)
    expect(errs({ codeExecutionUsdPerHour: "0.5" })).toEqual({})
    expect(errs({ codeExecutionUsdPerHour: "-1" }).codeExecutionUsdPerHour).toBeDefined()
  })

  it("sends only the changed fields, always with expectedVersion and the reason", () => {
    const body = settingsBody({ ...settingsValues(settings), graceDays: "5" }, "longer grace", settings)
    expect(body).toEqual({ graceDays: 5, expectedVersion: 4, reason: "longer grace" })
    const two = settingsBody({ ...settingsValues(settings), creditValidityMonths: "24", marginEgpPerUsd: "52.5" }, "r", settings)
    expect(two).toEqual({ creditValidityMonths: 24, marginEgpPerUsd: "52.5", expectedVersion: 4, reason: "r" })
  })

  it("clears an optional decimal with null, and does not call a re-typed same value a change", () => {
    expect(settingsBody({ ...settingsValues(settings), marginEgpPerUsd: "" }, "r", settings)).toMatchObject({ marginEgpPerUsd: null })
    const withHour = { ...settings, codeExecutionUsdPerHour: "0.500000" }
    expect(settingsBody({ ...settingsValues(withHour), codeExecutionUsdPerHour: "0.5" }, "r", withHour)).toEqual({ expectedVersion: 4, reason: "r" })
    expect(settingsBody({ ...settingsValues(settings), marginEgpPerUsd: "50.0" }, "r", settings)).toEqual({ expectedVersion: 4, reason: "r" })
  })

  it("refuses to save when nothing changed", () => {
    expect(settingsNothingChanged(settingsValues(settings), settings)).toEqual(["Nothing has changed. Change a value to save."])
    expect(settingsNothingChanged({ ...settingsValues(settings), graceDays: "4" }, settings)).toEqual([])
  })

  it("shows the unusual-price box only after the server asks, and sends it with a changed hour price", () => {
    const shown = (error: unknown) => visibleFields(SETTINGS_FIELDS, settingsValues(settings), error).some((f) => f.name === "confirmUnusualPrice")
    expect(shown(null)).toBe(false)
    expect(shown(api(422, "unusual_price"))).toBe(true)
    const ticked = { ...settingsValues(settings), codeExecutionUsdPerHour: "900", confirmUnusualPrice: true }
    expect(settingsBody(ticked, "r", settings)).toMatchObject({ codeExecutionUsdPerHour: "900", confirmUnusualPrice: true })
    expect(settingsBody({ ...settingsValues(settings), graceDays: "4", confirmUnusualPrice: true }, "r", settings)).not.toHaveProperty("confirmUnusualPrice")
  })
})

describe("credit conversion", () => {
  it("shows 1 EGP as 100 piasters without float drift", () => {
    expect(shiftDecimal("12.500000", 2)).toBe("1250")
    expect(shiftDecimal("0.125", 2)).toBe("12.5")
    expect(shiftDecimal("0.001", 2)).toBe("0.1")
    expect(unitsPerMajor("12.500000")).toBe("1,250")
    expect(unitsPerMajor("0.070000")).toBe("7")
    expect(trimDecimal("3.500000")).toBe("3.5")
    expect(trimDecimal("50")).toBe("50")
  })

  it("validates the rate: above zero, at most 6 places", () => {
    const e = (v: string) => fieldErrors(CREDIT_RATE_FIELDS, { unitsPerMinor: v }).unitsPerMinor
    expect(e("")).toBe("Units per piaster is required.")
    expect(e("0")).toMatch(/above 0/)
    expect(e("1.1234567")).toMatch(/6 decimal places/)
    expect(e("12.5")).toBeUndefined()
  })

  it("creates with a null expectedVersion and replaces with the version read", () => {
    expect(creditRateSetBody({ unitsPerMinor: "10" }, "first rate", null)).toEqual({ unitsPerMinor: "10", expectedVersion: null, reason: "first rate" })
    expect(creditRateSetBody({ unitsPerMinor: "15" }, "raise", fx.creditRate)).toEqual({ unitsPerMinor: "15", expectedVersion: 2, reason: "raise" })
    expect(creditRateUnchanged(creditRateValues(fx.creditRate), fx.creditRate)).toHaveLength(1)
    expect(creditRateUnchanged({ unitsPerMinor: "13" }, fx.creditRate)).toEqual([])
  })

  it("always confirms the stop when clearing", () => {
    expect(creditRateClearBody("retire it", fx.creditRate)).toEqual({ expectedVersion: 2, confirmStopConversions: true, reason: "retire it" })
  })
})

describe("AI token prices", () => {
  const values = (m: typeof tiered, over: Record<string, string | boolean> = {}) => ({ ...llmPriceValues(m), ...over })
  const noTier = { tierThresholdTokens: "", tier2InputUsdPerMtok: "", tier2OutputUsdPerMtok: "" }
  const names = (m: typeof tiered, v: Record<string, string | boolean>) => visibleFields(llmPriceFields(m), v, null).map((f) => f.name)

  it("starts from the override, else from the built-in price", () => {
    expect(llmPriceValues(tiered)).toMatchObject({ inputUsdPerMtok: "2", outputUsdPerMtok: "12", cachedInputUsdPerMtok: "0.2", tierThresholdTokens: "200000", tier2InputUsdPerMtok: "4" })
    expect(llmPriceValues(flat)).toMatchObject({ inputUsdPerMtok: "0.9", outputUsdPerMtok: "4.5" })
    expect(llmPriceValues(unpriced)).toMatchObject({ inputUsdPerMtok: "", outputUsdPerMtok: "" })
  })

  it("warns about a flat rate only for a tiered built-in row whose override has no tier 2", () => {
    expect(dropsTier(values(tiered), tiered)).toBe(false)
    expect(names(tiered, values(tiered))).not.toContain("dropsTierNotice")
    expect(dropsTier(values(tiered, noTier), tiered)).toBe(true)
    expect(names(tiered, values(tiered, noTier))).toEqual(expect.arrayContaining(["dropsTierNotice", "confirmDropTier"]))
    expect(dropsTier(values(flat, noTier), flat)).toBe(false)
    expect(names(flat, values(flat))).not.toContain("dropsTierNotice")
    expect(dropsTier(values(unpriced, noTier), unpriced)).toBe(false)
  })

  it("requires the flat-rate box to be ticked before it saves, and sends the flag only then", () => {
    const flatTiered = values(tiered, noTier)
    expect(llmConfirmChecks(flatTiered, tiered)).toHaveLength(1)
    const ticked = values(tiered, { ...noTier, confirmDropTier: true })
    expect(llmConfirmChecks(ticked, tiered)).toEqual([])
    expect(llmPriceBody(ticked, "r", tiered)).toMatchObject({ confirmDropTier: true })
    expect(llmPriceBody(values(tiered), "r", tiered)).not.toHaveProperty("confirmDropTier")
  })

  it("flags prices under 1/100 or over 100 times the built-in, and sends the flag when ticked", () => {
    expect(unusualRateNames(values(flat), flat)).toEqual([])
    expect(unusualRateNames(values(flat, { inputUsdPerMtok: "0.009" }), flat)).toEqual(["inputUsdPerMtok"])
    expect(unusualRateNames(values(flat, { outputUsdPerMtok: "501" }), flat)).toEqual(["outputUsdPerMtok"])
    expect(unusualRateNames(values(flat, { outputUsdPerMtok: "500" }), flat)).toEqual([])
    expect(unusualRateNames(values(unpriced, { inputUsdPerMtok: "9999" }), unpriced)).toEqual([])
    const typo = values(flat, { inputUsdPerMtok: "0.009" })
    expect(llmConfirmChecks(typo, flat)).toHaveLength(1)
    expect(llmPriceBody({ ...typo, confirmUnusualPrice: true }, "r", flat)).toMatchObject({ confirmUnusualPrice: true })
    expect(llmPriceBody(values(flat), "r", flat)).not.toHaveProperty("confirmUnusualPrice")
  })

  it("shows a confirmation the server asked for even when the form did not predict it", () => {
    const shown = (error: unknown) => visibleFields(llmPriceFields(flat), values(flat), error).map((f) => f.name)
    expect(shown(null)).not.toContain("confirmUnusualPrice")
    expect(shown(api(422, "unusual_price"))).toContain("confirmUnusualPrice")
    expect(shown(api(422, "override_drops_tier"))).toContain("confirmDropTier")
  })

  it("sends per-million prices as decimal strings, optional ones as null, and the version read", () => {
    const body = llmPriceBody(values(flat, { inputUsdPerMtok: "0.95", cachedInputUsdPerMtok: "0.100000" }), "match vendor", flat)
    expect(body).toEqual({
      inputUsdPerMtok: "0.95",
      outputUsdPerMtok: "4.5",
      cachedInputUsdPerMtok: "0.1",
      cacheWrite5mUsdPerMtok: null,
      cacheWrite1hUsdPerMtok: null,
      tierThresholdTokens: null,
      tier2InputUsdPerMtok: null,
      tier2OutputUsdPerMtok: null,
      expectedVersion: 3,
      reason: "match vendor",
    })
    expect(typeof body.inputUsdPerMtok).toBe("string")
    expect(llmPriceBody(values(tiered), "r", tiered)).toMatchObject({ expectedVersion: null, tierThresholdTokens: 200000, tier2InputUsdPerMtok: "4" })
  })

  it("needs input and output, bounds them, and keeps the three tier fields together", () => {
    const e = (m: typeof tiered, over: Record<string, string>) => fieldErrors(llmPriceFields(m), values(m, over))
    expect(e(unpriced, {}).inputUsdPerMtok).toBe("Input (USD per million tokens) is required.")
    expect(e(flat, { outputUsdPerMtok: "1001" }).outputUsdPerMtok).toMatch(/above 0 and at most 1,000/)
    expect(e(flat, { inputUsdPerMtok: "1.1234567" }).inputUsdPerMtok).toMatch(/6 decimal places/)
    expect(llmPriceChecks(values(flat))).toEqual([])
    expect(llmPriceChecks(values(tiered))).toEqual([])
    expect(llmPriceChecks(values(tiered, { tier2OutputUsdPerMtok: "" }))).toHaveLength(1)
    expect(llmPriceChecks(values(flat, { tierThresholdTokens: "1000" }))).toHaveLength(1)
  })

  it("clears with the version read", () => {
    expect(llmPriceClearBody("retire", { version: 3 })).toEqual({ expectedVersion: 3, reason: "retire" })
  })

  it("formats prices per million tokens", () => {
    expect(usdPerMtok("3.000000")).toBe("$3.00")
    expect(usdPerMtok("0.075000")).toBe("$0.075")
    expect(usdPerMtok("1250.5")).toBe("$1,250.50")
    expect(usdPerMtok(null)).toBe("None")
  })
})

describe("stale writes and friendly codes", () => {
  it("reads every reload code, and blocks the same submit afterwards", () => {
    for (const code of ["stale_write", "credit_rate_exists", "credit_rate_not_set", "llm_price_exists", "llm_price_not_set"]) {
      expect(isStaleWrite(api(409, code))).toBe(true)
    }
    expect(staleBlock(api(409, "stale_write"))).not.toBeNull()
    expect(isStaleWrite(api(409, "refund_in_flight"))).toBe(false)
    expect(isStaleWrite(api(422, "unusual_price"))).toBe(false)
    expect(staleBlock(null)).toBeNull()
  })

  it("says someone changed it, and names each new code in plain words", () => {
    const say = (status: number, code: string) => adminBillingFailureMessage(api(status, code), "save")
    expect(say(409, "stale_write")).toMatch(/^Someone changed this while you were editing\./)
    expect(say(409, "credit_rate_exists")).toMatch(/rate was set/)
    expect(say(404, "credit_rate_not_set")).toMatch(/no rate to clear|no longer exists/)
    expect(say(409, "llm_price_exists")).toMatch(/override was set/)
    expect(say(409, "llm_price_not_set")).toMatch(/no override to clear/)
    expect(say(422, "unusual_price")).toMatch(/Tick the box/)
    expect(say(422, "override_drops_tier")).toMatch(/flat rate/)
  })

  it("shows the server's own sentence for any other 422", () => {
    const err = new ApiError(422, "x", { code: "invalid_setting", message: "graceDays must be between 1 and 7." })
    expect(adminBillingFailureMessage(err, "save")).toBe("graceDays must be between 1 and 7.")
  })
})

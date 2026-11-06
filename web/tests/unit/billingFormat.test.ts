import { describe, expect, it } from "vitest"
import {
  estimateSentence,
  formatBillingDate,
  formatCredits,
  formatMoney,
  formatPercent,
  intervalLabel,
  isLiveSubscription,
  isPercentPayer,
  paymentPhase,
} from "@/lib/billingFormat"
import type { EstimateResponse } from "@/lib/billingTypes"

const est = (over: Partial<EstimateResponse>): EstimateResponse => ({
  low: 3,
  high: 5,
  payer: "credits",
  percentLow: null,
  percentHigh: null,
  blockedReason: null,
  ...over,
})

describe("billing formatting", () => {
  it("formats piasters as EGP with two decimals and the currency code", () => {
    expect(formatMoney(125000, "EGP", "en-US")).toMatch(/^EGP\s1,250\.00$/)
    expect(formatMoney(0, "EGP", "en-US")).toMatch(/^EGP\s0\.00$/)
  })

  it("pluralises credits and groups thousands", () => {
    expect(formatCredits(1, "en-US")).toBe("1 credit")
    expect(formatCredits(1240, "en-US")).toBe("1,240 credits")
  })

  it("rounds a fraction to a whole percentage and never goes negative", () => {
    expect(formatPercent(0.634)).toBe("63%")
    expect(formatPercent(1.2)).toBe("120%")
    expect(formatPercent(-0.1)).toBe("0%")
  })

  it("names the month so 8/11 cannot be misread", () => {
    expect(formatBillingDate("2026-11-14T00:00:00Z", "en-GB")).toBe("14 Nov 2026")
  })

  it("labels intervals", () => {
    expect(intervalLabel("month")).toBe("per month")
    expect(intervalLabel("year")).toBe("per year")
  })

  it("states a credit range with an en dash and a percent range against the plan or seat", () => {
    expect(estimateSentence(est({}))).toBe("3–5 credits")
    expect(estimateSentence(est({ low: 4, high: 4 }))).toBe("about 4 credits")
    expect(estimateSentence(est({ payer: "allowance", percentLow: 2, percentHigh: 4 }))).toBe("2–4% of your monthly plan")
    expect(estimateSentence(est({ payer: "allowance", percentLow: 0, percentHigh: 0 }))).toBe("under 1% of your monthly plan")
    expect(estimateSentence(est({ payer: "seat", percentLow: 1, percentHigh: 3 }))).toBe(
      "1–3% of your seat's monthly allowance",
    )
    expect(estimateSentence(est({ payer: "allowance", percentLow: null, percentHigh: null }))).toBe("3–5 credits")
    expect(estimateSentence(est({ payer: "none" }))).toBe("no charge")
  })

  it("knows which payers are shown as a percentage", () => {
    expect(isPercentPayer("allowance")).toBe(true)
    expect(isPercentPayer("seat")).toBe(true)
    expect(isPercentPayer("credits")).toBe(false)
    expect(isPercentPayer("none")).toBe(false)
  })

  it("treats pending-first-payment, active and past-due as a live subscription", () => {
    expect(isLiveSubscription("pending_first_payment")).toBe(true)
    expect(isLiveSubscription("active")).toBe(true)
    expect(isLiveSubscription("past_due")).toBe(true)
    expect(isLiveSubscription("cancelled")).toBe(false)
    expect(isLiveSubscription("expired")).toBe(false)
    expect(isLiveSubscription(undefined)).toBe(false)
  })

  it("groups payment statuses into the phases the return page shows", () => {
    expect(paymentPhase("created")).toBe("confirming")
    expect(paymentPhase("pending")).toBe("confirming")
    expect(paymentPhase("paid")).toBe("paid")
    expect(paymentPhase("failed")).toBe("failed")
    expect(paymentPhase("failed_mismatch")).toBe("mismatch")
    expect(paymentPhase("refunded")).toBe("reversed")
    expect(paymentPhase("partially_refunded")).toBe("reversed")
    expect(paymentPhase("voided")).toBe("reversed")
  })
})
